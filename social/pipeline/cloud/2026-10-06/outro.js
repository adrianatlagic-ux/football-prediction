export default async ({project,media,text,rect})=>{
 const p=await project({dir:'daily-outro',size:'720x1280',fps:24,background:'#080808'});
 const logo=await p.add('/home/user/logo.png');
 p.compose([
 rect({x:0,y:0,width:720,height:1280,fill:'#080808'}),
 media({file:logo,x:35,y:400,width:650,height:216.667,fit:'contain'}),
 text('goaliq.de',{x:35,y:684,width:650,height:83,fontFamily:'Montserrat',fontWeight:700,fontSize:55,align:'center',color:'#d4af37'}),
 text('AI predictions, for entertainment only.\nNo betting advice.',{x:35,y:1090,width:650,height:112,fontFamily:'Inter',fontSize:28,align:'center',color:'#ffffff'})
 ],{at:0,dur:3,name:'Original logo, domain and English disclaimer'});
 await p.frame(1,'renders/outro-review.png');
 await p.render('renders/outro-video.mp4',{depth:8,bitrate:10000000,concurrency:2});
};