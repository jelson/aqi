// https://github.com/esp8266/Arduino/blob/master/libraries/ESP8266HTTPClient/examples/BasicHttpsClient/BasicHttpsClient.ino
// https://randomnerdtutorials.com/esp8266-dht11dht22-temperature-and-humidity-web-server-with-arduino-ide/
#include <ESP8266WiFi.h>
#include <ESP8266WiFiMulti.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClientSecureBearSSL.h>
#include <NTPClient.h>  // https://github.com/arduino-libraries/NTPClient
#include <WiFiUdp.h>

#include <DHT.h>
#include <sstream>


// TODO:
// salted hashed password
// batching

// On the bigger boards pin 14 is labeled D5.
// On the little boards it's also labeled D5. Hooray!
#define DHTPIN  14  // https://randomnerdtutorials.com/esp8266-pinout-reference-gpios/
#define DHTTYPE DHT22

#define TEST_MODE       0

#if TEST_MODE

#define SAMPLE_PERIOD_SEC (8)
#define BATCH_SIZE        (10)
#define BACKLOG_LIMIT     (11)
#define FAILURE_MASK      (0)

#else
#define SAMPLE_PERIOD_SEC (300)   // 5 min
#define BATCH_SIZE        (1)    // upload once an hour
#define BACKLOG_LIMIT     (11)  // Big batches break with OOM anyway :v(
#endif

ESP8266WiFiMulti WiFiMulti;
#include "lectrobox_credentials.h"

DHT dht(DHTPIN, DHTTYPE);
WiFiUDP ntpUDP;
NTPClient timeClient(ntpUDP);

struct s_Sample {
  long epochTime;
  float temperature_C;
  float humidity_perc;
};
typedef struct s_Sample Sample;

Sample batch[BACKLOG_LIMIT];
int batch_count;
#if TEST_MODE
int simulate_failure;
#endif

// forward declarations
void reset_batch();


std::unique_ptr<BearSSL::WiFiClientSecure>client(new BearSSL::WiFiClientSecure);
HTTPClient https;

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);

  Serial.begin(115200);
  dht.begin();
  // Serial.setDebugOutput(true);

  Serial.println();
  Serial.println();
  Serial.println();

  for (uint8_t t = 2; t > 0; t--) {
    Serial.printf("[SETUP] WAIT %d...\n", t);
    Serial.flush();
    delay(1000);
  }

  WiFi.mode(WIFI_STA);
  registerAccessPoints();

  while (true) {
    if (WiFiMulti.run() == WL_CONNECTED) {
      break;
    }
    delay(500);
    Serial.print("...waiting for wifi");
  }

  timeClient.begin();

  Serial.print("MAC address:\t");
  Serial.println(WiFi.macAddress());
  Serial.print("IP address:\t");
  Serial.println(WiFi.localIP());

  client->setInsecure();
  learn_identity();
  
  reset_batch();
#if TEST_MODE
  simulate_failure = 0;
#endif
}

String identity;
bool client_needs_reset;
void learn_identity()
{
  while (true)
  {
    String url = String(LECTROBOX_IDENT_URL) + "?macaddr=" + WiFi.macAddress();
    https.begin(*client, url);
 
    Serial.printf("Identity request: %s\n", url.c_str());
  
    int httpCode = https.GET();
    if (httpCode > 0) {
      Serial.printf("[HTTP] POST... code: %d\n", httpCode);
    
      if (httpCode == HTTP_CODE_OK) {
        identity = https.getString();
        Serial.printf("Got identity: \"%s\"\n", identity.c_str());
        break;
      } else {
      }

      // Don't annoy server any more than we would with sample data.
      delay(SAMPLE_PERIOD_SEC * 1000);
    }
    https.end();
  }
  client_needs_reset = true; // I'm trying really hard to re-use this stupid object, but it remembers its URL even after .end().
}

void reset_batch() {
  batch_count=0;
}

void emitPreamble(std::stringstream* ss) {
  (*ss)
     << "{\n"
     << "  \"clowny-cleartext-password\": \"" << LECTROBOX_PASSWORD << "\",\n"
     << "  \"sensorname\": \"" << identity.c_str() << "\",\n"
     << "  \"sensordata\": [\n";
}

// Mystery: why can't I use my typedef Sample here!?
void emitSample(std::stringstream* ss, struct s_Sample* sample, int i) {
  if (i>0) {
    (*ss) << ",\n"; // stupid comma rule
  }
  
  (*ss)
     << "    {\n"
     << "      \"time\": " << sample->epochTime << ",\n"
     << "      \"temperature_C\": " << sample->temperature_C << ",\n"
     << "      \"humidity_perc\": " << sample->humidity_perc << "\n"
     << "    }\n";
}

void emitPostamble(std::stringstream* ss) {
  (*ss)
    << "  ]\n"
    << "}\n";
}

void emit(std::stringstream* ss) {
  emitPreamble(ss);
  for (int i=0; i<batch_count; i++) {
    emitSample(ss, &batch[i], i);
  }
  emitPostamble(ss);
}

struct Metrics {
  int total_samples;
  int upload_failures;
  int https_begins;
} metrics;

bool collect_sample() {
  if (batch_count >= BACKLOG_LIMIT) {
    Serial.printf("assertion failed: batch_count exceeds BACKLOG_LIMIT\n");
    return false;
  }
  Sample *sample = &batch[batch_count];
  sample->epochTime = timeClient.getEpochTime();
  sample->temperature_C = dht.readTemperature();
  sample->humidity_perc = dht.readHumidity();
  if (isnan(sample->temperature_C) || isnan(sample->humidity_perc)) {
    Serial.printf("Rejecting invalid (nan) sample\n");
    return false;
  }
  Serial.printf("Collecting sample #%d temp_c %.1f at epochTime %ld upload_failures %d https_begins %d\n",
    metrics.total_samples,
    sample->temperature_C,
    sample->epochTime,
    metrics.upload_failures, metrics.https_begins);
  metrics.total_samples += 1;
  batch_count += 1;

#if TEST_MODE
  simulate_failure += 1;
#endif
  return true;
}


bool upload_batch() {
  bool success = false;
  if (client_needs_reset || !https.connected()) {
    Serial.printf("Connecting https\n");
    https.begin(*client, LECTROBOX_DATA_URL);
    metrics.https_begins += 1;
    client_needs_reset = false; // don't keep doing this forever
  }
/*
  if (!https.connected()) {
    Serial.printf("https connection failed; abandoning post\n");
    return;
  }
*/
  std::stringstream ss;
  emit(&ss);

#if TEST_MODE
    bool fail = (simulate_failure & FAILURE_MASK);
    Serial.printf("simulate_failure %x fail %d\n", simulate_failure, fail);
    if (fail) {
      ss.str("");
      ss << "BORK";
    }
#endif

  Serial.print(ss.str().c_str());
  
  https.addHeader("Content-Type", "application/json");
  int httpCode = https.POST(ss.str().c_str());
  if (httpCode > 0) {
          // HTTP header has been send and Server response header has been handled
    Serial.printf("[HTTP] POST... code: %d\n", httpCode);

    // file found at server
    if (httpCode == HTTP_CODE_OK) {
      success = true;
      reset_batch();
    } else {
      success = false;
      metrics.upload_failures += 1;
    }
  } else {
    Serial.printf("[HTTP] POST... failed, error: %s\n", https.errorToString(httpCode).c_str());
    metrics.upload_failures += 1;
  }

  https.end();
  // Leave the connection open for later.
  return success;
}

String morseEncode(char x)
{
    // https://www.geeksforgeeks.org/morse-code-implementation/
    // refer to the Morse table
    // image attached in the article
    switch (x) {
    case 'a':
        return ".-";
    case 'b':
        return "-...";
    case 'c':
        return "-.-.";
    case 'd':
        return "-..";
    case 'e':
        return ".";
    case 'f':
        return "..-.";
    case 'g':
        return "--.";
    case 'h':
        return "....";
    case 'i':
        return "..";
    case 'j':
        return ".---";
    case 'k':
        return "-.-";
    case 'l':
        return ".-..";
    case 'm':
        return "--";
    case 'n':
        return "-.";
    case 'o':
        return "---";
    case 'p':
        return ".--.";
    case 'q':
        return "--.-";
    case 'r':
        return ".-.";
    case 's':
        return "...";
    case 't':
        return "-";
    case 'u':
        return "..-";
    case 'v':
        return "...-";
    case 'w':
        return ".--";
    case 'x':
        return "-..-";
    case 'y':
        return "-.--";
    case 'z':
        return "--..";
    case '1':
        return ".----";
    case '2':
        return "..---";
    case '3':
        return "...--";
    case '4':
        return "....-";
    case '5':
        return ".....";
    case '6':
        return "-....";
    case '7':
        return "--...";
    case '8':
        return "---..";
    case '9':
        return "----.";
    case '0':
        return "-----";
    default:
        return ".-.-.-.-";
    }
}

//bool message_A[20] = {1,0,1,1,0, 0,0,0,0,0, 0,0,0,0,0, 0,0,0,0,0};
bool message_B[20] = {1,1,0,1,0, 1,0,1,0,0, 0,0,0,0,0, 0,0,0,0,0};
bool message_1[20] = {1,0,1,1,0, 1,1,0,1,1, 0,1,1,0,0, 0,0,0,0,0}; // no sensor data
bool message_2[20] = {1,0,1,0,1, 1,0,1,1,0, 1,1,0,0,0, 0,0,0,00,}; // upload failed

struct Status {
  bool time_client_ok;
  bool collect_sample_ok;
  bool upload_ok;
};

void probe(long epochTime, struct Status *status) {
  status->time_client_ok = epochTime > 32000000;  // It's past 1970 :v)
  status->collect_sample_ok = collect_sample();
  status->upload_ok= true;
  if (batch_count >= BATCH_SIZE) {
        Serial.printf("batch_count %d limit %d uploading\n", batch_count, BATCH_SIZE);
    status->upload_ok = upload_batch();
  }
  if (batch_count >= BACKLOG_LIMIT) {
    Serial.printf("Exceeded backlog limit %d; resetting\n", BACKLOG_LIMIT);
    // protect the invariant that we don't write beyond batch buffer.
    // in principle we could have a circular buffer, but ... meh.
    reset_batch();
  }
}

void blink_letter(char letter) {
  String morse = morseEncode(letter);
  for (int i=0; i<morse.length(); i++) {
    digitalWrite(LED_BUILTIN, LOW);  // Low turns on LED
    delay(morse[i]=='-' ? 400 : 200);
    Serial.print(morse[i]);
    digitalWrite(LED_BUILTIN, HIGH);
    delay(200);
  }
  Serial.print(letter);
  delay(600);
}

void loop() {
  struct Status status;
  long epochTime = timeClient.getEpochTime();
  long nextProbeDue = epochTime + SAMPLE_PERIOD_SEC;
  timeClient.update();

  probe(epochTime, &status);

  long timeRemaining = nextProbeDue - timeClient.getEpochTime();
  while (timeRemaining > 0) {
    Serial.print("Status code: ");
    blink_letter('c'); // Current version code
    // blink out error statusus in morse
    if (!status.time_client_ok) {
      blink_letter('1');
    }
    if (!status.collect_sample_ok) {
      blink_letter('2');
    }
    if (!status.upload_ok) {
      blink_letter('3');
    }
    delay(2000);
    timeRemaining = nextProbeDue - timeClient.getEpochTime();
    Serial.printf("  ...next probe due %ds\n", (int) timeRemaining);
  }
}
