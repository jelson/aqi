#define LECTROBOX_PASSWORD  "PASSWORD_HERE"
#define LECTROBOX_DATA_URL   "https://airquality.circlemud.org/data"
#define LECTROBOX_IDENT_URL  "https://airquality.circlemud.org/mac_lookup"

void registerAccessPoints() {
  WiFiMulti.addAP("essid", "wpa-password");
}
