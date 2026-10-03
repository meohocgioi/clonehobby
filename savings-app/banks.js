// Danh sách ngân hàng tại Việt Nam — nguồn: vi.wikipedia.org/wiki/Danh_sách_ngân_hàng_tại_Việt_Nam
// Logo: icons/banks/ (VietQR / Wikipedia). Ngân hàng không có logo sẽ hiện chữ viết tắt.
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
  "a": []
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
  ]
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
  ]
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
  "logo": "icons/banks/BVB.png",
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
  "g": "Ngân hàng trong nước (chuyển giao bắt buộc)",
  "logo": null,
  "a": []
 },
 {
  "n": "MBV",
  "f": "Việt Nam Hiện Đại",
  "g": "Ngân hàng trong nước (chuyển giao bắt buộc)",
  "logo": "icons/banks/MBV.png",
  "a": []
 },
 {
  "n": "GPBank",
  "f": "Kỷ Nguyên Thịnh Vượng",
  "g": "Ngân hàng trong nước (chuyển giao bắt buộc)",
  "logo": "icons/banks/GPB.png",
  "a": []
 },
 {
  "n": "Vikki Bank",
  "f": "Số Vikki",
  "g": "Ngân hàng trong nước (chuyển giao bắt buộc)",
  "logo": "icons/banks/Vikki.png",
  "a": []
 },
 {
  "n": "IVB",
  "f": "Indovina",
  "g": "Ngân hàng liên doanh",
  "logo": "icons/banks/IVB.png",
  "a": []
 },
 {
  "n": "VRB",
  "f": "Việt – Nga",
  "g": "Ngân hàng liên doanh",
  "logo": "icons/banks/VRB.png",
  "a": []
 },
 {
  "n": "Woori Bank",
  "f": "Woori Việt Nam",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/WVN.png",
  "a": []
 },
 {
  "n": "UOB",
  "f": "UOB Việt Nam",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/UOB.png",
  "a": []
 },
 {
  "n": "HSBC",
  "f": "HSBC Việt Nam",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/HSBC.png",
  "a": []
 },
 {
  "n": "Public Bank",
  "f": "Public Việt Nam",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/PBVN.png",
  "a": []
 },
 {
  "n": "Standard Chartered",
  "f": "Standard Chartered Việt Nam",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/SCVN.png",
  "a": []
 },
 {
  "n": "Shinhan Bank",
  "f": "Shinhan Việt Nam",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/SHBVN.png",
  "a": []
 },
 {
  "n": "CIMB Bank",
  "f": "CIMB Việt Nam",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/CIMB.png",
  "a": []
 },
 {
  "n": "HongLeong Bank",
  "f": "Hong Leong Việt Nam",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "ANZ",
  "f": "ANZ Việt Nam",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/w_Australia_and_New_Zealand_Banking_Group.png",
  "a": []
 },
 {
  "n": "Citibank",
  "f": "Citibank Việt Nam",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/CITIBANK.png",
  "a": []
 },
 {
  "n": "JP Morgan Chase",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Wells Fargo",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "RBI",
  "f": "Raiffeisen International",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Bank of India",
  "f": "Ấn Độ",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": [
   "BOI"
  ]
 },
 {
  "n": "Bank of Taiwan",
  "f": "Đài Loan",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/w_Ngân_hàng_Đài_Loan.png",
  "a": [
   "BOT"
  ]
 },
 {
  "n": "Chinatrust Bank",
  "f": "CTBC",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Cathay United",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Taipei Fubon",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "First Commercial",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "E.Sun Commercial",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Hua Nan Commercial",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Taishin International Bank",
  "f": "Quốc tế Đài Tân",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/w_Ngân_hàng_quốc_tế_Taishin.png",
  "a": []
 },
 {
  "n": "Sinopac",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "UBOT",
  "f": "Union Bank of Taiwan",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Shanghai Commercial & Savings",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Taiwan Shin Kong Commercial",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "DB",
  "f": "Deutsche Việt Nam",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/w_Deutsche_Bank.png",
  "a": []
 },
 {
  "n": "Commerzbank",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/w_Commerzbank.png",
  "a": []
 },
 {
  "n": "LBBW",
  "f": "Landesbank Baden-Wuerttemberg",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "ING",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Kookmin",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "KEB Hana",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Industrial Bank of Korea",
  "f": "Công nghiệp Hàn Quốc",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": [
   "IBK"
  ]
 },
 {
  "n": "NHBank",
  "f": "Nonghyup",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/NHB HN.png",
  "a": []
 },
 {
  "n": "Korea Development Bank",
  "f": "Phát triển Hàn Quốc",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": [
   "KDB"
  ]
 },
 {
  "n": "Korea Eximbank",
  "f": "Xuất nhập khẩu Hàn Quốc",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": [
   "KEXIM"
  ]
 },
 {
  "n": "BNK",
  "f": "Busan",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "iM (Daegu)",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Maybank",
  "f": "Malayan Banking Berhad",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": [
   "MBB"
  ]
 },
 {
  "n": "Mitsubishi UFJ Financial Group",
  "f": "MUFG",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "SMBC",
  "f": "Sumitomo Mitsui Banking Corporation",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Mizuho",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Resona",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Hiroshima",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "JBIC",
  "f": "Hợp tác quốc tế Nhật Bản",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Joyo",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Juroku",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Senshu Ikeda",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "BNP Paribas",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/w_BNP_Paribas.png",
  "a": []
 },
 {
  "n": "BPCE IOM",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "SocGen",
  "f": "Société Générale",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "ODDO BHF",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "QNB",
  "f": "Qatar National",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "DBS",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/DBS.png",
  "a": []
 },
 {
  "n": "OCBC",
  "f": "Oversea Chinese Banking Corporation",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "KBank",
  "f": "Đại chúng Kasikornbank",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/KBank.png",
  "a": []
 },
 {
  "n": "Siam Commercial",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Bangkok Bank",
  "f": "Bangkok Đại chúng",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "ICBC",
  "f": "Công thương Trung Quốc",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/w_Ngân_hàng_Công_Thương_Trung_Quốc.png",
  "a": []
 },
 {
  "n": "Agricultural Bank of China",
  "f": "Nông nghiệp Trung Quốc",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": [
   "AgBank"
  ]
 },
 {
  "n": "China Construction Bank",
  "f": "Xây dựng Trung Quốc",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": [
   "CCB"
  ]
 },
 {
  "n": "BOCHK",
  "f": "Bank of China (Hong Kong)",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/w_Ngân_hàng_Trung_Quốc.png",
  "a": []
 },
 {
  "n": "BankComm",
  "f": "Bank of Communications",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "Intesa Sanpaolo",
  "f": "",
  "g": "Ngân hàng nước ngoài",
  "logo": null,
  "a": []
 },
 {
  "n": "ADB Vietnam Resident Mission",
  "f": "Cơ quan đại diện thường trú Ngân hàng Phát triển châu Á",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/w_Ngân_hàng_Phát_triển_châu_Á.png",
  "a": []
 },
 {
  "n": "WB",
  "f": "Chi nhánh Ngân hàng Thế giới tại Việt Nam",
  "g": "Ngân hàng nước ngoài",
  "logo": "icons/banks/w_Ngân_hàng_Thế_giới.png",
  "a": []
 },
 {
  "n": "NHCSXH",
  "f": "Chính sách xã hội",
  "g": "Ngân hàng chính sách",
  "logo": "icons/banks/w_Ngân_hàng_Chính_sách_xã_hội.png",
  "a": [
   "VBSP"
  ]
 },
 {
  "n": "VDB",
  "f": "Phát triển Việt Nam",
  "g": "Ngân hàng chính sách",
  "logo": null,
  "a": []
 }
];
