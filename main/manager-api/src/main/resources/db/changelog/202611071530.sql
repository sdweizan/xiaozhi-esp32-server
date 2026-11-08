-- 设备定向 OTA：为每台设备增加可绑定的固件ID
-- ota_id 为空时保持原有「按 board 型号取最新固件」的广播行为
SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'ai_device'
      AND COLUMN_NAME = 'ota_id'
);
SET @sql = IF(@col_exists = 0,
    'ALTER TABLE `ai_device` ADD COLUMN `ota_id` varchar(64) NULL DEFAULT NULL COMMENT ''定向绑定固件ID，为空则按型号广播'' AFTER `app_version`',
    'SELECT ''column already exists, skip'' AS msg');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
