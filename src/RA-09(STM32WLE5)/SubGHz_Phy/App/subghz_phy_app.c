#include "subghz_phy_app.h"

#include "ra09_modem.h"
#include "stm32_seq.h"
#include "subg_command.h"
#include "utilities_def.h"

static void command_process_notify(void)
{
  UTIL_SEQ_SetTask(1UL << CFG_SEQ_Task_Vcom, CFG_SEQ_Prio_1);
}

void SubghzApp_Init(void)
{
  UTIL_SEQ_RegTask(1UL << CFG_SEQ_Task_Vcom, UTIL_SEQ_RFU, CMD_Process);
  UTIL_SEQ_RegTask(1UL << CFG_SEQ_Task_LoraProcess,
                   UTIL_SEQ_RFU,
                   RA09_ModemRadioProcess);

  RA09_ModemInit();
  CMD_Init(command_process_notify);
}
