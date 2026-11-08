package xiaozhi.modules.device.vo;

import lombok.Data;

/**
 * 设备可绑定的固件选项（不暴露固件文件路径等敏感字段）
 */
@Data
public class DeviceOtaOptionVO {

    private String id;

    private String firmwareName;

    private String type;

    private String version;
}
