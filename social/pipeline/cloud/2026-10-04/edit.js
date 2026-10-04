export default async ({project,text}) => {
 const p=await project({dir:'goalfiq-final',size:'486x864',fps:24,background:'#101010'});
 const en=await p.add('/home/user/english.mp4');
 const action=await p.add('/home/user/action.mp4');
 const outro=await p.add('/home/user/outro.mp4');
 p.cut(en,{from:0,dur:4,at:0,fit:'cover'});
 p.cut(action,{dur:4.5,at:4,fit:'cover'});
 p.cut(en,{from:4,dur:4,at:8.5,fit:'cover'});
 p.cut(outro,{dur:2,at:12.5,fit:'cover'});
 p.compose([
 text('Goalfiq',{x:24,y:294,width:438,height:72,fontFamily:'Montserrat',fontWeight:700,fontSize:58,align:'center',color:'#d4af37'}),
 text('Who breaks through?',{x:24,y:387,width:438,height:44,fontFamily:'Inter',fontSize:24,align:'center',color:'#ffffff'}),
 text('goalfiq.de',{x:24,y:463,width:438,height:50,fontFamily:'Montserrat',fontWeight:700,fontSize:34,align:'center',color:'#d4af37'}),
 text('Fictional anime · No predicted score',{x:18,y:730,width:450,height:28,fontFamily:'Inter',fontSize:16,align:'center',color:'#bcbcbc'})
 ],{at:12.5,dur:2,name:'Goalfiq English outro'});
 await p.add('/home/user/bed.wav');
};