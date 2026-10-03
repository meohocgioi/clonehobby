// Ngân hàng trong nước — nguồn: vi.wikipedia.org/wiki/Danh_sách_ngân_hàng_tại_Việt_Nam
// Logo hình vuông (biểu tượng) nằm trong icons/banks/. Ngân hàng không có logo sẽ hiện chữ viết tắt.
// t:1 = ảnh là ô vuông đủ màu (logo chữ trên nền màu thương hiệu).
const BANK_LIST = [
 {
  "n": "Agribank",
  "f": "Nông nghiệp và Phát triển Nông thôn Việt Nam",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/VBA.png",
  "a": []
 },
 {
  "n": "Vietcombank",
  "f": "Ngoại thương Việt Nam",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/VCB.png",
  "a": [
   "VCB",
   "VCB"
  ]
 },
 {
  "n": "VPBank",
  "f": "Việt Nam Thịnh Vượng",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/VPB.png",
  "a": [
   "VPB"
  ]
 },
 {
  "n": "Techcombank",
  "f": "Kỹ Thương Việt Nam",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/TCB.png",
  "a": [
   "TCB"
  ]
 },
 {
  "n": "BIDV",
  "f": "Đầu tư và Phát triển Việt Nam",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/BIDV.png",
  "a": [
   "BID"
  ]
 },
 {
  "n": "MBBank",
  "f": "Quân đội",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/MB.png",
  "a": [
   "MBB",
   "MB Bank",
   "MB"
  ]
 },
 {
  "n": "VietinBank",
  "f": "Công Thương Việt Nam",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/ICB.png",
  "a": [
   "CTG",
   "CTG",
   "Vietin"
  ]
 },
 {
  "n": "ACB",
  "f": "Á Châu",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/ACB.png",
  "a": [],
  "t": 1
 },
 {
  "n": "SHB",
  "f": "Sài Gòn – Hà Nội",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/SHB.png",
  "a": []
 },
 {
  "n": "HDBank",
  "f": "Phát triển Thành phố Hồ Chí Minh",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/HDB.png",
  "a": [
   "HDB"
  ]
 },
 {
  "n": "VIB",
  "f": "Quốc tế Việt Nam",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/VIB.png",
  "a": []
 },
 {
  "n": "LPBank",
  "f": "Lộc Phát Việt Nam",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/LPB.png",
  "a": [
   "LPB"
  ]
 },
 {
  "n": "SeABank",
  "f": "Đông Nam Á",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/SEAB.png",
  "a": [
   "SSB"
  ]
 },
 {
  "n": "TPBank",
  "f": "Tiên Phong",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/TPB.png",
  "a": [
   "TPB"
  ]
 },
 {
  "n": "MSB",
  "f": "Hàng hải Việt Nam",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/MSB.png",
  "a": []
 },
 {
  "n": "OCB",
  "f": "Phương Đông",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/OCB.png",
  "a": []
 },
 {
  "n": "SCB",
  "f": "Sài Gòn",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/SCB.png",
  "a": []
 },
 {
  "n": "Sacombank",
  "f": "Sài Gòn Tài Lộc",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/STB.png",
  "a": [
   "STB"
  ],
  "t": 1
 },
 {
  "n": "Eximbank",
  "f": "Xuất Nhập khẩu Việt Nam",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/EIB.png",
  "a": [
   "EIB"
  ]
 },
 {
  "n": "Nam A Bank",
  "f": "Nam Á",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/NAB.png",
  "a": [
   "NAB",
   "NamABank"
  ],
  "t": 1
 },
 {
  "n": "NCB",
  "f": "Quốc Dân",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/NCB.png",
  "a": []
 },
 {
  "n": "ABBANK",
  "f": "An Bình",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/ABB.png",
  "a": [
   "ABB"
  ]
 },
 {
  "n": "Bac A Bank",
  "f": "Bắc Á",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/BAB.png",
  "a": [
   "BAB"
  ]
 },
 {
  "n": "PVCombank",
  "f": "Đại Chúng Việt Nam",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/PVCB.png",
  "a": []
 },
 {
  "n": "VietBank",
  "f": "Việt Nam Thương Tín",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/VIETBANK.png",
  "a": [
   "VBB"
  ]
 },
 {
  "n": "BVBank",
  "f": "Bản Việt",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/VCCB.png",
  "a": [
   "BVB"
  ]
 },
 {
  "n": "Viet A Bank",
  "f": "Việt Á",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/VAB.png",
  "a": [
   "VAB"
  ]
 },
 {
  "n": "PGBank",
  "f": "Thịnh vượng và Phát triển",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/PGB.png",
  "a": [
   "PGB"
  ]
 },
 {
  "n": "Kienlongbank",
  "f": "Kiên Long",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/KLB.png",
  "a": [
   "KLB"
  ]
 },
 {
  "n": "Saigonbank",
  "f": "Sài Gòn Công Thương",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/SGICB.png",
  "a": [
   "SGB"
  ]
 },
 {
  "n": "Baoviet Bank",
  "f": "Bảo Việt",
  "g": "Ngân hàng trong nước",
  "logo": "icons/banks/BVB.png",
  "a": []
 },
 {
  "n": "VCBNeo",
  "f": "Ngoại thương Công nghệ số",
  "g": "Ngân hàng chuyển giao bắt buộc",
  "logo": null,
  "a": []
 },
 {
  "n": "MBV",
  "f": "Việt Nam Hiện Đại",
  "g": "Ngân hàng chuyển giao bắt buộc",
  "logo": "icons/banks/MBV.png",
  "a": [],
  "t": 1
 },
 {
  "n": "GPBank",
  "f": "Kỷ Nguyên Thịnh Vượng",
  "g": "Ngân hàng chuyển giao bắt buộc",
  "logo": "icons/banks/GPB.png",
  "a": []
 },
 {
  "n": "Vikki Bank",
  "f": "Số Vikki",
  "g": "Ngân hàng chuyển giao bắt buộc",
  "logo": "icons/banks/Vikki.png",
  "a": []
 }
];
