/**
 * EPaper Driver Test for reTerminal E1001 (7.5" B&W, UC8179)
 *
 * Library:  GxEPD2 (https://github.com/ZinggJM/GxEPD2)
 * Board:    XIAO_ESP32S3  (Tools > Board > ESP32 Arduino > XIAO_ESP32S3)
 * PSRAM:    OPI PSRAM     (Tools > PSRAM > OPI PSRAM)
 * Upload:   115200 baud   (Tools > Upload Speed > 115200)
 *
 * Pins (reTerminal E1001):
 *   EPD: SCK=7, MOSI=9, CS=10, DC=11, RST=12, BUSY=13
 *   SD (deselect to avoid SPI conflict): EN=16, CS=14
 *   Battery enable: GPIO21
 *   Serial1: TX=43, RX=44
 */

#include <SPI.h>
#include <GxEPD2_BW.h>
#include <Fonts/FreeMonoBold9pt7b.h>
#include <Fonts/FreeMonoBold18pt7b.h>

// --- Pin Definitions ---
#define EPD_SCK_PIN   7
#define EPD_MOSI_PIN  9
#define EPD_CS_PIN    10
#define EPD_DC_PIN    11
#define EPD_RES_PIN   12
#define EPD_BUSY_PIN  13

#define SD_EN_PIN     16   // SD power enable
#define SD_CS_PIN     14   // SD chip select (must stay HIGH to deselect)

#define BAT_EN_PIN    21   // Battery monitoring enable

#define SERIAL_RX     44
#define SERIAL_TX     43

// --- GxEPD2 Display Setup ---
// GxEPD2_750_GDEY075T7 is the confirmed driver for E1001 (UC8179, 800x480 B&W)
#define MAX_DISPLAY_BUFFER_SIZE 65536ul
#define MAX_HEIGHT(EPD) (EPD::HEIGHT <= MAX_DISPLAY_BUFFER_SIZE / (EPD::WIDTH / 8) \
                         ? EPD::HEIGHT : MAX_DISPLAY_BUFFER_SIZE / (EPD::WIDTH / 8))

SPIClass hspi(HSPI);
GxEPD2_BW<GxEPD2_750_GDEY075T7, MAX_HEIGHT(GxEPD2_750_GDEY075T7)>
    display(GxEPD2_750_GDEY075T7(EPD_CS_PIN, EPD_DC_PIN, EPD_RES_PIN, EPD_BUSY_PIN));

void setup() {
  // Enable battery circuit
  pinMode(BAT_EN_PIN, OUTPUT);
  digitalWrite(BAT_EN_PIN, HIGH);

  // Deselect SD card BEFORE initialising SPI to prevent bus conflict
  pinMode(SD_CS_PIN, OUTPUT);
  digitalWrite(SD_CS_PIN, HIGH);
  pinMode(SD_EN_PIN, OUTPUT);
  digitalWrite(SD_EN_PIN, HIGH);

  // Serial for debug
  Serial1.begin(115200, SERIAL_8N1, SERIAL_RX, SERIAL_TX);
  delay(500);
  Serial1.println("\n\n=== E1001 EPaper Test ===");

  // Init HSPI (MISO not needed for e-paper)
  hspi.begin(EPD_SCK_PIN, /*MISO*/ -1, EPD_MOSI_PIN, /*SS*/ -1);

  // Init display
  display.epd2.selectSPI(hspi, SPISettings(4000000, MSBFIRST, SPI_MODE0));
  display.init(115200);

  Serial1.println("Display init OK, drawing test pattern...");

  drawTestPattern();

  display.hibernate();
  Serial1.println("Done. Display hibernated.");
}

void drawTestPattern() {
  display.setRotation(0);
  display.setFullWindow();
  display.firstPage();

  do {
    display.fillScreen(GxEPD_WHITE);

    // --- Top black banner ---
    display.fillRect(0, 0, 800, 60, GxEPD_BLACK);
    display.setFont(&FreeMonoBold18pt7b);
    display.setTextColor(GxEPD_WHITE);
    display.setCursor(220, 45);
    display.print("reTerminal E1001 TEST");

    // --- Outer border ---
    display.drawRect(2, 62, 796, 416, GxEPD_BLACK);
    display.drawRect(4, 64, 792, 412, GxEPD_BLACK);

    // --- Center cross-hair ---
    display.drawLine(400, 64, 400, 476, GxEPD_BLACK);
    display.drawLine(4, 270, 796, 270, GxEPD_BLACK);

    // --- Corner filled squares (20x20) ---
    display.fillRect(10, 70, 40, 40, GxEPD_BLACK);   // top-left
    display.fillRect(750, 70, 40, 40, GxEPD_BLACK);  // top-right
    display.fillRect(10, 426, 40, 40, GxEPD_BLACK);  // bottom-left
    display.fillRect(750, 426, 40, 40, GxEPD_BLACK); // bottom-right

    // --- Gradient gray bars (simulated with dithered rects) ---
    for (int i = 0; i < 8; i++) {
      int x = 60 + i * 80;
      if (i % 2 == 0) {
        display.fillRect(x, 80, 70, 30, GxEPD_BLACK);
      } else {
        display.drawRect(x, 80, 70, 30, GxEPD_BLACK);
      }
    }

    // --- Center text ---
    display.setFont(&FreeMonoBold18pt7b);
    display.setTextColor(GxEPD_BLACK);
    // Center "GxEPD2 OK" at ~400, 270
    display.setCursor(260, 260);
    display.print("GxEPD2 OK");

    // --- Smaller labels ---
    display.setFont(&FreeMonoBold9pt7b);
    display.setCursor(20, 300);
    display.print("Driver: GxEPD2_750_GDEY075T7");
    display.setCursor(20, 320);
    display.print("Board:  ESP32-S3  PSRAM: OPI");
    display.setCursor(20, 340);
    display.print("Pins:   CS=10 DC=11 RST=12 BUSY=13");
    display.setCursor(20, 360);
    display.print("SPI:    SCK=7 MOSI=9 (HSPI)");

  } while (display.nextPage());
}

void loop() {
  delay(60000);
}
