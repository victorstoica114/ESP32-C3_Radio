#ifndef RA09_MODEM_H
#define RA09_MODEM_H

#include <stdint.h>

void RA09_ModemInit(void);
void RA09_ModemOnUartByte(uint8_t byte);
void RA09_ModemCommandProcess(void);
void RA09_ModemRadioProcess(void);

#endif
