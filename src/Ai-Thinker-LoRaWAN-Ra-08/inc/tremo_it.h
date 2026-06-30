#ifndef __TREMO_IT_H
#define __TREMO_IT_H

#ifdef __cplusplus
extern "C" {
#endif

void NMI_Handler(void);
void HardFault_Handler(void);
void MemManage_Handler(void);
void BusFault_Handler(void);
void UsageFault_Handler(void);
void SVC_Handler(void);
void PendSV_Handler(void);
void SysTick_Handler(void);
void PWR_IRQHandler(void);
void LORA_IRQHandler(void);
void RTC_IRQHandler(void);
void UART0_IRQHandler(void);

#ifdef __cplusplus
}
#endif

#endif
