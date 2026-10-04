export default async ({project,media,text,rect})=>{
 const p=await project({dir:'logo-outro',size:'496x864',fps:24,background:'#080808'});
 const bg=await p.add('/home/user/gold.mp4'); const logo=await p.add('/home/user/logo.png');
 p.cut(bg,{dur:3});
 p.compose([
 rect({x:0,y:0,width:496,height:864,fill:'#080808',opacity:0.62}),
 media({file:logo,x:24,y:270,width:448,height:149.333,fit:'contain'}),
 text('goaliq.de',{x:24,y:462,width:448,height:56,fontFamily:'Montserrat',fontWeight:700,fontSize:38,align:'center',color:'#d4af37'}),
 text('AI predictions, for entertainment only.\nNo betting advice.',{x:24,y:736,width:448,height:76,fontFamily:'Inter',fontSize:19,align:'center',color:'#ffffff'})
 ],{at:0,dur:3,name:'Original logo, domain and English disclaimer'});
 await p.frame(1.5,'renders/review.png');
 await p.render('renders/outro-video.mp4',{depth:8,bitrate:4000000,concurrency:2});
};