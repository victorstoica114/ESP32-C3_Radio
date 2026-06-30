# Third-Party Notices

The project source code is licensed under the MIT License unless a file says
otherwise.

Third-party dependencies are not vendored in this repository, but are pulled by
PlatformIO according to `platformio.ini`. They remain under their own licenses:

| Dependency | Source | License |
| --- | --- | --- |
| RadioLib | https://github.com/jgromes/RadioLib | MIT |
| U8g2 | https://github.com/olikraus/u8g2 | BSD-2-Clause; bundled fonts may have their own terms |
| LoRa_E32_Series_Library | https://github.com/xreef/LoRa_E32_Series_Library | MIT |
| Arduino-ESP32 / Espressif32 PlatformIO platform | PlatformIO package manager | Upstream Espressif/Arduino package licenses |

The files under `Datasheets/` are vendor or manufacturer documentation kept for
local hardware reference. They are not covered by this project's MIT License.
Before making the repository public, either confirm that each PDF can be
redistributed or replace the PDFs with links to the official source pages.

The RA-08 module-side firmware is maintained in a separate repository:
https://github.com/victorstoica114/RA-08_AT-Commands
