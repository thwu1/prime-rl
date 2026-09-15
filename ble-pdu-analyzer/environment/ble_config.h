#ifndef BLE_CONFIG_H
#define BLE_CONFIG_H

/*
 * nRF52840 BLE Peripheral Configuration
 * Project: Nordic_HRM Sensor
 * SDK: nRF5 SDK v17.1.0
 * SoftDevice: S140 v7.3.0
 */

#define DEVICE_NAME                "Nordic_HRM"
#define DEVICE_APPEARANCE          0x0340    /* Generic Heart Rate Sensor */

/* Advertising parameters */
#define ADV_INTERVAL_UNITS         160       /* 100 ms in 0.625ms units */
#define ADV_TIMEOUT_SEC            180
#define ADV_TYPE                   BLE_GAP_ADV_TYPE_CONNECTABLE_SCANNABLE_UNDIRECTED

/* Channel configuration */
#define ADV_CHANNEL_MAP            (BLE_GAP_ADV_CH_37 | BLE_GAP_ADV_CH_38 | BLE_GAP_ADV_CH_39)

/* Address */
#define ADDR_TYPE                  BLE_GAP_ADDR_TYPE_RANDOM_STATIC
#define DEVICE_ADDR                {0xF2, 0xE7, 0x8B, 0x19, 0xA4, 0xC3}  /* LSB-first */

/* Radio TX Power */
#define TX_POWER_DBM               4

/* Service UUIDs to advertise */
#define SVC_UUID_HEART_RATE        0x180D
#define SVC_UUID_BATTERY           0x180F

/* Manufacturer Specific Data */
#define COMPANY_ID_NORDIC          0x0059
#define MSD_PAYLOAD                {0x01, 0x02, 0x03, 0x04}

/* GAP Advertising Flags */
#define ADV_FLAGS_VALUE            (BLE_GAP_ADV_FLAG_LE_GENERAL_DISC_MODE | \
                                    BLE_GAP_ADV_FLAG_BR_EDR_NOT_SUPPORTED)
/* = 0x06 */

#endif /* BLE_CONFIG_H */
