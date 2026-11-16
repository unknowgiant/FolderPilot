// 主题皮肤清单（自动生成，请勿手改；见 src/tools/gen_skins.py）
// prev 为壁纸缺失时的兜底渐变；wall 为皮肤缩略图，sur 为该主题的面板底色。
export const SKINS = [
  {key: 'default', name: '晨雾蓝', cat: '默认', slogan: '出厂外观', acc: '#4a7fd0',
   wall: '', scheme: '', prev: 'linear-gradient(165deg,#f7f9fd,#e8eff9 60%,#dfe9f6)'},
  {key: "yunhai", name: "云海初醒", cat: "风景", slogan: "每一帧，都是新的开始", acc: "#C08A46", sur: "#FFFFFF",
   wall: "skins/yunhai.webp", scheme: "light", prev: "linear-gradient(160deg, #FFFFFF, #E7DCCA)"},
  {key: "xinghe", name: "星河入梦", cat: "风景", slogan: "把夜色，留给专注", acc: "#7FA6DC", sur: "#16233A",
   wall: "skins/xinghe.webp", scheme: "dark", prev: "linear-gradient(160deg, #16233A, #0A1424)"},
  {key: "hupan", name: "湖畔微风", cat: "风景", slogan: "风起时，记得抬头", acc: "#C7A76C", sur: "#FFFFFF",
   wall: "skins/hupan.webp", scheme: "light", prev: "linear-gradient(160deg, #FFFFFF, #EFEDE2)"},
  {key: "mose", name: "墨色千山", cat: "国风", slogan: "山高水长，静水深流", acc: "#A7342A", sur: "#FFFFFF",
   wall: "skins/mose.webp", scheme: "light", prev: "linear-gradient(160deg, #FFFFFF, #F4F1E8)"},
  {key: "zhuying", name: "竹影清风", cat: "国风", slogan: "疏影横斜，清风自来", acc: "#7C9B7E", sur: "#FFFFFF",
   wall: "skins/zhuying.webp", scheme: "light", prev: "linear-gradient(160deg, #FFFFFF, #EFEDE7)"},
  {key: "qinghua", name: "青花山河", cat: "国风", slogan: "一笔青花，万顷江山", acc: "#A8C1D9", sur: "#FFFFFF",
   wall: "skins/qinghua.webp", scheme: "light", prev: "linear-gradient(160deg, #FFFFFF, #F3F5F4)"},
  {key: "hongri", name: "红日东方", cat: "红色", slogan: "山河为证，初心不改", acc: "#EFA25F", sur: "#3A1E19",
   wall: "skins/hongri.webp", scheme: "dark", prev: "linear-gradient(160deg, #3A1E19, #331C18)"},
  {key: "chicheng", name: "赤诚", cat: "红色", slogan: "赤子之心，山河不忘", acc: "#C8A46A", sur: "#1E1113",
   wall: "skins/chicheng.webp", scheme: "dark", prev: "linear-gradient(160deg, #1E1113, #130A0B)"},
  {key: "yaodong", name: "窑洞灯火", cat: "复古", slogan: "星星之火，可以燎原", acc: "#E2AE5B", sur: "#1C2836",
   wall: "skins/yaodong.webp", scheme: "dark", prev: "linear-gradient(160deg, #1C2836, #15202E)"},
  {key: "shishi", name: "实事求是", cat: "复古", slogan: "没有调查，就没有发言权", acc: "#9C5B36", sur: "#4A3B2E",
   wall: "skins/shishi.webp", scheme: "dark", prev: "linear-gradient(160deg, #4A3B2E, #3B2E23)"},
];
export const SKIN_KEYS = SKINS.map(s => s.key);
export const skinOf = k => SKINS.find(s => s.key === k) || SKINS[0];
