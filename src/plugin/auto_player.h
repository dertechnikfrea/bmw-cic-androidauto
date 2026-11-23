#ifndef CIC_AUTO_PLAYER_H
#define CIC_AUTO_PLAYER_H
/* HMI-thread-only policy. No sleep, native calls, retries or guessed ACKs here.
 * Backend is the real IBA adapter or the deterministic host test adapter. */
enum AutoPhase { AUTO_IDLE, AUTO_STARTING, AUTO_PLAYING, AUTO_STOPPING, AUTO_BLOCKED };
struct AutoPlayer {
 int phase,mode,last_op,error;
 long since,step_since,playing_since;
 char reason[160];
 void reset(){phase=AUTO_IDLE;mode=0;last_op=-1;error=0;since=step_since=playing_since=0;reason[0]=0;}
 int active()const{return phase==AUTO_STARTING||phase==AUTO_PLAYING||phase==AUTO_STOPPING;}
 static void copy(char* to,const char* from,unsigned cap){unsigned i=0;for(;from&&from[i]&&i+1<cap;++i)to[i]=from[i];to[i]=0;}
 template<class B> bool begin(B& b,int selected,long now){
  if(selected<0||selected>2){b.message("Unknown player.");return false;}
  if(active()||b.busy()) {b.message("A session is active or a close is pending. Press Stop.");return false;}
  if(!b.preflight(selected))return false;
  if(b.state().ready&&!b.state().untouched()&&!b.restart()) {
   b.message("Cannot prepare another session: close pending.");return false;
  }
  mode=selected;b.select(mode);phase=AUTO_STARTING;last_op=-1;error=0;reason[0]=0;
  since=step_since=now;b.message("Preparing player...");return true;
 }
 template<class B> void stop(B& b,long now){
  if(phase!=AUTO_STOPPING){phase=AUTO_STOPPING;since=now;last_op=-1;}
  b.message("Stopping and releasing resources...");
 }
 template<class B> void fail(B& b,const char* why,long now){
  copy(reason,why,sizeof reason);error=1;stop(b,now);
 }
 template<class B> void tick(B& b,long now){
  if(!active())return;
  IbaState& s=b.state();
  if(phase==AUTO_STOPPING){
   if(!b.held()) {phase=AUTO_IDLE;b.message(error?(reason[0]?reason:"Error; resources released."):"Stopped.");return;}
   if((unsigned long)(now-since)>20000UL){phase=AUTO_BLOCKED;b.message("Close not confirmed. Resources held; Stop retries.");return;}
   b.step(1,now);
   if(s.next()==IBA_FAILED&&!s.pending()) {phase=AUTO_BLOCKED;b.message("The CIC refused the close. Resources held; check the logs.");return;}
   if(s.next()==IBA_DONE&&!b.held()){phase=AUTO_IDLE;b.message(error?(reason[0]?reason:"Error; resources released."):"Stopped.");}
   return;
  }
  s.expire(now);
  if(s.failed){fail(b,s.pending()?"Timeout waiting for CIC confirmation.":b.last_message(),now);return;}
  if(phase==AUTO_PLAYING){
   int child=b.helper_status();
   if(child>0){if(child==2)fail(b,"The player ended with an error; check the logs.",now);else stop(b,now);return;}
   if(!b.unlimited()&&(unsigned long)(now-playing_since)>60000UL)stop(b,now);
   return;
  }
  if(!s.ready){
   b.prepare();
   if(!s.ready)fail(b,b.last_message(),now);
   return;
  }
  IbaOp op=s.next();
  if(op!=last_op){last_op=op;step_since=now;}
  if((unsigned long)(now-step_since)>12000UL){fail(b,"Timeout preparing the video; closing the session.",now);return;}
  if(op==IBA_PLAYING){phase=AUTO_PLAYING;playing_since=now;b.message("Player started.");return;}
  if(op==IBA_FAILED){fail(b,b.last_message(),now);return;}
  // One request per tick; a pending ACK/deck never causes duplicate native sends.
  b.step(0,now);
  if(s.failed){fail(b,b.last_message(),now);return;}
  switch(s.next()) {
   case IBA_AUDIO:b.message("Connecting audio...");break;
   case IBA_FILE:b.message("Opening video...");break;
   case IBA_CONNECT:b.message("Connecting display...");break;
   case IBA_START:b.message("Starting video...");break;
   case IBA_SHOW:b.message("Preparing picture...");break;
   case IBA_WAIT:b.message("Waiting for the CIC...");break;
   default:break;
  }
 }
};
#endif
