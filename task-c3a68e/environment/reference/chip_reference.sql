-- STM32H753ZI Chip Cross-Reference Database
-- Peripheral pin multiplexing, DMA channel mappings, and interrupt vectors
-- Source: STM32H753ZI Reference Manual (RM0433) and Datasheet

CREATE TABLE peripherals (
    name TEXT PRIMARY KEY,
    bus TEXT NOT NULL,
    base_address INTEGER NOT NULL,
    size INTEGER NOT NULL,
    exclusive_group TEXT
);

CREATE TABLE dma_channels (
    controller TEXT NOT NULL,
    stream INTEGER NOT NULL,
    channel INTEGER NOT NULL,
    peripheral TEXT NOT NULL,
    direction TEXT NOT NULL,
    PRIMARY KEY (controller, stream, channel)
);

CREATE TABLE pin_assignments (
    pin TEXT NOT NULL,
    af_number INTEGER NOT NULL,
    peripheral TEXT NOT NULL,
    function TEXT NOT NULL,
    PRIMARY KEY (pin, af_number)
);

CREATE TABLE interrupt_vectors (
    irq_name TEXT PRIMARY KEY,
    vector_number INTEGER NOT NULL,
    peripheral TEXT NOT NULL,
    default_priority INTEGER NOT NULL
);

-- =========================================================================
-- Peripheral bus assignments
-- =========================================================================

INSERT INTO peripherals VALUES ('rcc', 'AHB4', 1476460544, 1024, NULL);
INSERT INTO peripherals VALUES ('gpio_a', 'AHB4', 1476395008, 1024, 'gpio');
INSERT INTO peripherals VALUES ('gpio_b', 'AHB4', 1476396032, 1024, 'gpio');
INSERT INTO peripherals VALUES ('gpio_c', 'AHB4', 1476397056, 1024, 'gpio');
INSERT INTO peripherals VALUES ('gpio_d', 'AHB4', 1476398080, 1024, 'gpio');
INSERT INTO peripherals VALUES ('gpio_e', 'AHB4', 1476399104, 1024, 'gpio');
INSERT INTO peripherals VALUES ('gpio_f', 'AHB4', 1476400128, 1024, 'gpio');
INSERT INTO peripherals VALUES ('gpio_g', 'AHB4', 1476401152, 1024, 'gpio');
INSERT INTO peripherals VALUES ('gpio_h', 'AHB4', 1476402176, 1024, 'gpio');
INSERT INTO peripherals VALUES ('usart1', 'APB2', 1073811456, 1024, NULL);
INSERT INTO peripherals VALUES ('usart2', 'APB1', 1073759232, 1024, NULL);
INSERT INTO peripherals VALUES ('usart3', 'APB1', 1073760256, 1024, NULL);
INSERT INTO peripherals VALUES ('usart6', 'APB2', 1073812480, 1024, NULL);
INSERT INTO peripherals VALUES ('spi1', 'APB2', 1073819648, 1024, NULL);
INSERT INTO peripherals VALUES ('spi2', 'APB1', 1073756160, 1024, NULL);
INSERT INTO peripherals VALUES ('spi3', 'APB1', 1073757184, 1024, NULL);
INSERT INTO peripherals VALUES ('spi4', 'APB2', 1073820672, 1024, NULL);
INSERT INTO peripherals VALUES ('i2c1', 'APB1', 1073763328, 1024, NULL);
INSERT INTO peripherals VALUES ('i2c2', 'APB1', 1073764352, 1024, NULL);
INSERT INTO peripherals VALUES ('i2c3', 'APB1', 1073765376, 1024, NULL);
INSERT INTO peripherals VALUES ('i2c4', 'APB4', 1476544512, 1024, NULL);
INSERT INTO peripherals VALUES ('eth_mac', 'AHB1', 1073905664, 8192, NULL);
INSERT INTO peripherals VALUES ('tim1', 'APB2', 1073807360, 1024, NULL);
INSERT INTO peripherals VALUES ('tim2', 'APB1', 1073741824, 1024, NULL);
INSERT INTO peripherals VALUES ('tim3', 'APB1', 1073742848, 1024, NULL);
INSERT INTO peripherals VALUES ('tim4', 'APB1', 1073743872, 1024, NULL);
INSERT INTO peripherals VALUES ('tim5', 'APB1', 1073744896, 1024, NULL);
INSERT INTO peripherals VALUES ('tim6', 'APB1', 1073745920, 1024, NULL);
INSERT INTO peripherals VALUES ('tim7', 'APB1', 1073746944, 1024, NULL);
INSERT INTO peripherals VALUES ('tim8', 'APB2', 1073808384, 1024, NULL);
INSERT INTO peripherals VALUES ('adc1', 'AHB1', 1073872896, 1024, NULL);
INSERT INTO peripherals VALUES ('adc2', 'AHB1', 1073873920, 1024, NULL);
INSERT INTO peripherals VALUES ('hash', 'AHB2', 1207964672, 1024, 'crypto_hw');
INSERT INTO peripherals VALUES ('rng', 'AHB2', 1207965696, 1024, 'crypto_hw');
INSERT INTO peripherals VALUES ('cryp', 'AHB2', 1207963648, 1024, 'crypto_hw');
INSERT INTO peripherals VALUES ('flash_ctrl', 'AHB3', 1375739904, 1024, NULL);
INSERT INTO peripherals VALUES ('quadspi', 'AHB3', 1375752192, 1024, NULL);
INSERT INTO peripherals VALUES ('syscfg', 'APB4', 1476395008, 1024, NULL);
INSERT INTO peripherals VALUES ('dma1', 'AHB1', 1073872896, 1024, 'dma');
INSERT INTO peripherals VALUES ('can1', 'APB1', 1073767424, 1024, NULL);
INSERT INTO peripherals VALUES ('dac1', 'APB1', 1073771520, 1024, NULL);

-- =========================================================================
-- DMA channel mappings (DMAMUX request routing)
-- =========================================================================

-- DMA1 streams
INSERT INTO dma_channels VALUES ('dma1', 0, 0, 'spi1', 'rx');
INSERT INTO dma_channels VALUES ('dma1', 0, 1, 'i2c1', 'rx');
INSERT INTO dma_channels VALUES ('dma1', 0, 3, 'tim4', 'ch1');
INSERT INTO dma_channels VALUES ('dma1', 1, 0, 'spi1', 'tx');
INSERT INTO dma_channels VALUES ('dma1', 1, 1, 'tim2', 'up');
INSERT INTO dma_channels VALUES ('dma1', 1, 3, 'i2c3', 'rx');
INSERT INTO dma_channels VALUES ('dma1', 2, 0, 'hash', 'in');
INSERT INTO dma_channels VALUES ('dma1', 2, 1, 'i2c1', 'tx');
INSERT INTO dma_channels VALUES ('dma1', 2, 3, 'usart3', 'rx');
INSERT INTO dma_channels VALUES ('dma1', 3, 0, 'spi2', 'rx');
INSERT INTO dma_channels VALUES ('dma1', 3, 1, 'tim3', 'ch4');
INSERT INTO dma_channels VALUES ('dma1', 3, 3, 'i2c2', 'rx');
INSERT INTO dma_channels VALUES ('dma1', 4, 0, 'spi2', 'tx');
INSERT INTO dma_channels VALUES ('dma1', 4, 1, 'usart1', 'tx');
INSERT INTO dma_channels VALUES ('dma1', 4, 3, 'tim5', 'ch2');
INSERT INTO dma_channels VALUES ('dma1', 5, 0, 'usart1', 'rx');
INSERT INTO dma_channels VALUES ('dma1', 5, 1, 'i2c2', 'tx');
INSERT INTO dma_channels VALUES ('dma1', 5, 3, 'tim5', 'ch1');
INSERT INTO dma_channels VALUES ('dma1', 6, 0, 'i2c3', 'tx');
INSERT INTO dma_channels VALUES ('dma1', 6, 1, 'usart2', 'rx');
INSERT INTO dma_channels VALUES ('dma1', 6, 3, 'tim3', 'ch1');
INSERT INTO dma_channels VALUES ('dma1', 7, 0, 'usart2', 'tx');
INSERT INTO dma_channels VALUES ('dma1', 7, 1, 'adc1', 'dr');
INSERT INTO dma_channels VALUES ('dma1', 7, 3, 'tim1', 'ch1');

-- DMA2 streams (DMA2 controller — separate from DMA1)
INSERT INTO dma_channels VALUES ('dma2', 0, 0, 'adc1', 'dr');
INSERT INTO dma_channels VALUES ('dma2', 0, 1, 'spi4', 'rx');
INSERT INTO dma_channels VALUES ('dma2', 0, 3, 'tim8', 'ch1');
INSERT INTO dma_channels VALUES ('dma2', 1, 0, 'spi4', 'tx');
INSERT INTO dma_channels VALUES ('dma2', 1, 1, 'usart6', 'rx');
INSERT INTO dma_channels VALUES ('dma2', 1, 3, 'tim1', 'ch1');
INSERT INTO dma_channels VALUES ('dma2', 2, 0, 'usart6', 'tx');
INSERT INTO dma_channels VALUES ('dma2', 2, 1, 'tim8', 'ch2');
INSERT INTO dma_channels VALUES ('dma2', 3, 0, 'spi1', 'rx');
INSERT INTO dma_channels VALUES ('dma2', 3, 1, 'tim8', 'ch3');
INSERT INTO dma_channels VALUES ('dma2', 4, 0, 'spi1', 'tx');
INSERT INTO dma_channels VALUES ('dma2', 4, 1, 'usart1', 'tx');
INSERT INTO dma_channels VALUES ('dma2', 5, 0, 'usart1', 'rx');
INSERT INTO dma_channels VALUES ('dma2', 5, 1, 'tim1', 'up');
INSERT INTO dma_channels VALUES ('dma2', 6, 0, 'cryp', 'in');
INSERT INTO dma_channels VALUES ('dma2', 6, 1, 'tim1', 'ch3');
INSERT INTO dma_channels VALUES ('dma2', 7, 0, 'cryp', 'out');
INSERT INTO dma_channels VALUES ('dma2', 7, 1, 'hash', 'in');

-- =========================================================================
-- Pin multiplexing (Alternate Function mappings)
-- AF -1 = analog mode (no alternate function)
-- =========================================================================

-- Port A
INSERT INTO pin_assignments VALUES ('PA0', 0, 'tim2', 'CH1');
INSERT INTO pin_assignments VALUES ('PA0', 1, 'tim5', 'CH1');
INSERT INTO pin_assignments VALUES ('PA0', -1, 'adc1', 'IN0');
INSERT INTO pin_assignments VALUES ('PA1', 0, 'tim2', 'CH2');
INSERT INTO pin_assignments VALUES ('PA1', 1, 'tim5', 'CH2');
INSERT INTO pin_assignments VALUES ('PA1', -1, 'adc1', 'IN1');
INSERT INTO pin_assignments VALUES ('PA2', 0, 'tim2', 'CH3');
INSERT INTO pin_assignments VALUES ('PA2', 7, 'usart2', 'TX');
INSERT INTO pin_assignments VALUES ('PA3', 0, 'tim2', 'CH4');
INSERT INTO pin_assignments VALUES ('PA3', 7, 'usart2', 'RX');
INSERT INTO pin_assignments VALUES ('PA4', -1, 'adc1', 'IN18');
INSERT INTO pin_assignments VALUES ('PA4', 5, 'spi1', 'NSS');
INSERT INTO pin_assignments VALUES ('PA4', 6, 'spi3', 'NSS');
INSERT INTO pin_assignments VALUES ('PA5', -1, 'adc1', 'IN19');
INSERT INTO pin_assignments VALUES ('PA5', 5, 'spi1', 'SCK');
INSERT INTO pin_assignments VALUES ('PA6', 2, 'tim3', 'CH1');
INSERT INTO pin_assignments VALUES ('PA6', 5, 'spi1', 'MISO');
INSERT INTO pin_assignments VALUES ('PA7', 2, 'tim3', 'CH2');
INSERT INTO pin_assignments VALUES ('PA7', 5, 'spi1', 'MOSI');
INSERT INTO pin_assignments VALUES ('PA8', 1, 'tim1', 'CH1');
INSERT INTO pin_assignments VALUES ('PA8', 4, 'i2c3', 'SCL');
INSERT INTO pin_assignments VALUES ('PA9', 7, 'usart1', 'TX');
INSERT INTO pin_assignments VALUES ('PA9', 4, 'i2c3', 'SMBA');
INSERT INTO pin_assignments VALUES ('PA10', 7, 'usart1', 'RX');
INSERT INTO pin_assignments VALUES ('PA11', 10, 'eth_mac', 'TX_CLK');
INSERT INTO pin_assignments VALUES ('PA12', 10, 'eth_mac', 'TX_EN');
INSERT INTO pin_assignments VALUES ('PA15', 1, 'tim2', 'CH1');
INSERT INTO pin_assignments VALUES ('PA15', 5, 'spi1', 'NSS');
INSERT INTO pin_assignments VALUES ('PA15', 6, 'spi3', 'NSS');

-- Port B
INSERT INTO pin_assignments VALUES ('PB0', 1, 'tim1', 'CH2N');
INSERT INTO pin_assignments VALUES ('PB0', 2, 'tim3', 'CH3');
INSERT INTO pin_assignments VALUES ('PB1', 1, 'tim1', 'CH3N');
INSERT INTO pin_assignments VALUES ('PB1', 2, 'tim3', 'CH4');
INSERT INTO pin_assignments VALUES ('PB3', 1, 'tim2', 'CH2');
INSERT INTO pin_assignments VALUES ('PB3', 5, 'spi1', 'SCK');
INSERT INTO pin_assignments VALUES ('PB3', 6, 'spi3', 'SCK');
INSERT INTO pin_assignments VALUES ('PB4', 2, 'tim3', 'CH1');
INSERT INTO pin_assignments VALUES ('PB4', 5, 'spi1', 'MISO');
INSERT INTO pin_assignments VALUES ('PB4', 6, 'spi3', 'MISO');
INSERT INTO pin_assignments VALUES ('PB5', 2, 'tim3', 'CH2');
INSERT INTO pin_assignments VALUES ('PB5', 5, 'spi1', 'MOSI');
INSERT INTO pin_assignments VALUES ('PB5', 6, 'spi3', 'MOSI');
INSERT INTO pin_assignments VALUES ('PB6', 4, 'i2c1', 'SCL');
INSERT INTO pin_assignments VALUES ('PB6', 7, 'usart1', 'TX');
INSERT INTO pin_assignments VALUES ('PB7', 4, 'i2c1', 'SDA');
INSERT INTO pin_assignments VALUES ('PB7', 7, 'usart1', 'RX');
INSERT INTO pin_assignments VALUES ('PB8', 4, 'i2c1', 'SCL');
INSERT INTO pin_assignments VALUES ('PB8', 2, 'tim4', 'CH3');
INSERT INTO pin_assignments VALUES ('PB9', 4, 'i2c1', 'SDA');
INSERT INTO pin_assignments VALUES ('PB9', 2, 'tim4', 'CH4');
INSERT INTO pin_assignments VALUES ('PB10', 1, 'tim2', 'CH3');
INSERT INTO pin_assignments VALUES ('PB10', 4, 'i2c2', 'SCL');
INSERT INTO pin_assignments VALUES ('PB10', 5, 'spi2', 'SCK');
INSERT INTO pin_assignments VALUES ('PB11', 1, 'tim2', 'CH4');
INSERT INTO pin_assignments VALUES ('PB11', 4, 'i2c2', 'SDA');
INSERT INTO pin_assignments VALUES ('PB12', 5, 'spi2', 'NSS');
INSERT INTO pin_assignments VALUES ('PB13', 5, 'spi2', 'SCK');
INSERT INTO pin_assignments VALUES ('PB13', 4, 'i2c2', 'SCL');
INSERT INTO pin_assignments VALUES ('PB14', 5, 'spi2', 'MISO');
INSERT INTO pin_assignments VALUES ('PB14', 4, 'i2c2', 'SDA');
INSERT INTO pin_assignments VALUES ('PB15', 5, 'spi2', 'MOSI');

-- Port C
INSERT INTO pin_assignments VALUES ('PC1', 11, 'eth_mac', 'MDC');
INSERT INTO pin_assignments VALUES ('PC2', 5, 'spi2', 'MISO');
INSERT INTO pin_assignments VALUES ('PC3', 5, 'spi2', 'MOSI');
INSERT INTO pin_assignments VALUES ('PC4', 11, 'eth_mac', 'RXD0');
INSERT INTO pin_assignments VALUES ('PC5', 11, 'eth_mac', 'RXD1');
INSERT INTO pin_assignments VALUES ('PC6', 2, 'tim3', 'CH1');
INSERT INTO pin_assignments VALUES ('PC6', 8, 'usart6', 'TX');
INSERT INTO pin_assignments VALUES ('PC7', 2, 'tim3', 'CH2');
INSERT INTO pin_assignments VALUES ('PC7', 8, 'usart6', 'RX');
INSERT INTO pin_assignments VALUES ('PC8', 2, 'tim3', 'CH3');
INSERT INTO pin_assignments VALUES ('PC9', 2, 'tim3', 'CH4');
INSERT INTO pin_assignments VALUES ('PC10', 7, 'usart3', 'TX');
INSERT INTO pin_assignments VALUES ('PC11', 7, 'usart3', 'RX');
INSERT INTO pin_assignments VALUES ('PC12', 6, 'spi3', 'MOSI');

-- Port D
INSERT INTO pin_assignments VALUES ('PD0', 9, 'can1', 'RX');
INSERT INTO pin_assignments VALUES ('PD1', 9, 'can1', 'TX');
INSERT INTO pin_assignments VALUES ('PD3', 5, 'spi2', 'SCK');
INSERT INTO pin_assignments VALUES ('PD5', 7, 'usart2', 'TX');
INSERT INTO pin_assignments VALUES ('PD6', 7, 'usart2', 'RX');
INSERT INTO pin_assignments VALUES ('PD8', 7, 'usart3', 'TX');
INSERT INTO pin_assignments VALUES ('PD9', 7, 'usart3', 'RX');
INSERT INTO pin_assignments VALUES ('PD12', 4, 'i2c1', 'SCL');
INSERT INTO pin_assignments VALUES ('PD12', 2, 'tim4', 'CH1');
INSERT INTO pin_assignments VALUES ('PD13', 4, 'i2c1', 'SDA');
INSERT INTO pin_assignments VALUES ('PD13', 2, 'tim4', 'CH2');
INSERT INTO pin_assignments VALUES ('PD14', 2, 'tim4', 'CH3');
INSERT INTO pin_assignments VALUES ('PD15', 2, 'tim4', 'CH4');

-- Port E
INSERT INTO pin_assignments VALUES ('PE2', 5, 'spi4', 'SCK');
INSERT INTO pin_assignments VALUES ('PE4', 5, 'spi4', 'NSS');
INSERT INTO pin_assignments VALUES ('PE5', 5, 'spi4', 'MISO');
INSERT INTO pin_assignments VALUES ('PE6', 5, 'spi4', 'MOSI');
INSERT INTO pin_assignments VALUES ('PE7', 1, 'tim1', 'ETR');
INSERT INTO pin_assignments VALUES ('PE8', 1, 'tim1', 'CH1N');
INSERT INTO pin_assignments VALUES ('PE9', 1, 'tim1', 'CH1');
INSERT INTO pin_assignments VALUES ('PE10', 1, 'tim1', 'CH2N');
INSERT INTO pin_assignments VALUES ('PE11', 1, 'tim1', 'CH2');
INSERT INTO pin_assignments VALUES ('PE11', 5, 'spi4', 'NSS');
INSERT INTO pin_assignments VALUES ('PE12', 1, 'tim1', 'CH3N');
INSERT INTO pin_assignments VALUES ('PE12', 5, 'spi1', 'SCK');
INSERT INTO pin_assignments VALUES ('PE13', 1, 'tim1', 'CH3');
INSERT INTO pin_assignments VALUES ('PE13', 5, 'spi1', 'MISO');
INSERT INTO pin_assignments VALUES ('PE14', 1, 'tim1', 'CH4');
INSERT INTO pin_assignments VALUES ('PE14', 5, 'spi1', 'MOSI');
INSERT INTO pin_assignments VALUES ('PE15', 1, 'tim1', 'BKIN');

-- Port F
INSERT INTO pin_assignments VALUES ('PF0', 4, 'i2c2', 'SDA');
INSERT INTO pin_assignments VALUES ('PF1', 4, 'i2c2', 'SCL');
INSERT INTO pin_assignments VALUES ('PF6', 2, 'tim5', 'ETR');
INSERT INTO pin_assignments VALUES ('PF7', 5, 'spi1', 'SCK');
INSERT INTO pin_assignments VALUES ('PF8', 5, 'spi1', 'MISO');
INSERT INTO pin_assignments VALUES ('PF9', 5, 'spi1', 'MOSI');
INSERT INTO pin_assignments VALUES ('PF14', 4, 'i2c4', 'SCL');
INSERT INTO pin_assignments VALUES ('PF15', 4, 'i2c4', 'SDA');

-- Port G
INSERT INTO pin_assignments VALUES ('PG9', 7, 'usart6', 'RX');
INSERT INTO pin_assignments VALUES ('PG14', 7, 'usart6', 'TX');

-- Port H
INSERT INTO pin_assignments VALUES ('PH4', 4, 'i2c2', 'SCL');
INSERT INTO pin_assignments VALUES ('PH5', 4, 'i2c2', 'SDA');
INSERT INTO pin_assignments VALUES ('PH7', 4, 'i2c3', 'SCL');
INSERT INTO pin_assignments VALUES ('PH8', 4, 'i2c3', 'SDA');
INSERT INTO pin_assignments VALUES ('PH11', 4, 'i2c4', 'SCL');
INSERT INTO pin_assignments VALUES ('PH12', 4, 'i2c4', 'SDA');

-- =========================================================================
-- Interrupt vector table
-- =========================================================================

INSERT INTO interrupt_vectors VALUES ('wwdg_irq', 0, 'wwdg', 0);
INSERT INTO interrupt_vectors VALUES ('pvd_avd_irq', 1, 'pwr', 1);
INSERT INTO interrupt_vectors VALUES ('flash_irq', 4, 'flash_ctrl', 3);
INSERT INTO interrupt_vectors VALUES ('rcc_irq', 5, 'rcc', 3);
INSERT INTO interrupt_vectors VALUES ('dma1_str0_irq', 11, 'dma1', 4);
INSERT INTO interrupt_vectors VALUES ('dma1_str1_irq', 12, 'dma1', 4);
INSERT INTO interrupt_vectors VALUES ('dma1_str2_irq', 13, 'dma1', 4);
INSERT INTO interrupt_vectors VALUES ('dma1_str3_irq', 14, 'dma1', 4);
INSERT INTO interrupt_vectors VALUES ('dma1_str4_irq', 15, 'dma1', 4);
INSERT INTO interrupt_vectors VALUES ('dma1_str5_irq', 16, 'dma1', 4);
INSERT INTO interrupt_vectors VALUES ('dma1_str6_irq', 17, 'dma1', 4);
INSERT INTO interrupt_vectors VALUES ('adc_irq', 18, 'adc1', 5);
INSERT INTO interrupt_vectors VALUES ('tim1_brk_irq', 24, 'tim1', 6);
INSERT INTO interrupt_vectors VALUES ('tim1_up_irq', 25, 'tim1', 6);
INSERT INTO interrupt_vectors VALUES ('tim1_trg_irq', 26, 'tim1', 6);
INSERT INTO interrupt_vectors VALUES ('tim1_cc_irq', 27, 'tim1', 6);
INSERT INTO interrupt_vectors VALUES ('tim2_irq', 28, 'tim2', 8);
INSERT INTO interrupt_vectors VALUES ('tim3_irq', 29, 'tim3', 8);
INSERT INTO interrupt_vectors VALUES ('tim4_irq', 30, 'tim4', 8);
INSERT INTO interrupt_vectors VALUES ('i2c1_ev_irq', 31, 'i2c1', 5);
INSERT INTO interrupt_vectors VALUES ('i2c1_er_irq', 32, 'i2c1', 5);
INSERT INTO interrupt_vectors VALUES ('i2c2_ev_irq', 33, 'i2c2', 5);
INSERT INTO interrupt_vectors VALUES ('i2c2_er_irq', 34, 'i2c2', 5);
INSERT INTO interrupt_vectors VALUES ('spi1_irq', 35, 'spi1', 6);
INSERT INTO interrupt_vectors VALUES ('spi2_irq', 36, 'spi2', 6);
INSERT INTO interrupt_vectors VALUES ('usart1_irq', 37, 'usart1', 7);
INSERT INTO interrupt_vectors VALUES ('usart2_irq', 38, 'usart2', 7);
INSERT INTO interrupt_vectors VALUES ('usart3_irq', 39, 'usart3', 7);
INSERT INTO interrupt_vectors VALUES ('tim5_irq', 50, 'tim5', 8);
INSERT INTO interrupt_vectors VALUES ('spi3_irq', 51, 'spi3', 6);
INSERT INTO interrupt_vectors VALUES ('dma1_str7_irq', 47, 'dma1', 4);
INSERT INTO interrupt_vectors VALUES ('tim6_irq', 54, 'tim6', 8);
INSERT INTO interrupt_vectors VALUES ('tim7_irq', 55, 'tim7', 8);
INSERT INTO interrupt_vectors VALUES ('dma2_str0_irq', 56, 'dma2', 4);
INSERT INTO interrupt_vectors VALUES ('dma2_str1_irq', 57, 'dma2', 4);
INSERT INTO interrupt_vectors VALUES ('dma2_str2_irq', 58, 'dma2', 4);
INSERT INTO interrupt_vectors VALUES ('dma2_str3_irq', 59, 'dma2', 4);
INSERT INTO interrupt_vectors VALUES ('dma2_str4_irq', 60, 'dma2', 4);
INSERT INTO interrupt_vectors VALUES ('eth_irq', 61, 'eth_mac', 4);
INSERT INTO interrupt_vectors VALUES ('dma2_str5_irq', 68, 'dma2', 4);
INSERT INTO interrupt_vectors VALUES ('dma2_str6_irq', 69, 'dma2', 4);
INSERT INTO interrupt_vectors VALUES ('dma2_str7_irq', 70, 'dma2', 4);
INSERT INTO interrupt_vectors VALUES ('usart6_irq', 71, 'usart6', 7);
INSERT INTO interrupt_vectors VALUES ('i2c3_ev_irq', 72, 'i2c3', 5);
INSERT INTO interrupt_vectors VALUES ('i2c3_er_irq', 73, 'i2c3', 5);
INSERT INTO interrupt_vectors VALUES ('rng_irq', 80, 'rng', 10);
INSERT INTO interrupt_vectors VALUES ('spi4_irq', 84, 'spi4', 6);
INSERT INTO interrupt_vectors VALUES ('quadspi_irq', 92, 'quadspi', 6);
INSERT INTO interrupt_vectors VALUES ('i2c4_ev_irq', 95, 'i2c4', 5);
INSERT INTO interrupt_vectors VALUES ('i2c4_er_irq', 96, 'i2c4', 5);
INSERT INTO interrupt_vectors VALUES ('tim8_brk_irq', 43, 'tim8', 6);
INSERT INTO interrupt_vectors VALUES ('tim8_up_irq', 44, 'tim8', 6);
INSERT INTO interrupt_vectors VALUES ('tim8_trg_irq', 45, 'tim8', 6);
INSERT INTO interrupt_vectors VALUES ('tim8_cc_irq', 46, 'tim8', 6);
INSERT INTO interrupt_vectors VALUES ('hash_rng_irq', 80, 'hash', 10);
