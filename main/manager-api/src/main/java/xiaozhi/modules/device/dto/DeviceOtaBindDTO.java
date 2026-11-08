package xiaozhi.modules.device.dto;

import java.io.Serializable;

import lombok.Data;

/**
 * 设备定向绑定固件请求
 * otaId 为空表示清除绑定，回退到按型号取最新固件
 */
@Data
public class DeviceOtaBindDTO implements Serializable {

    private String otaId;

    private static final long serialVersionUID = 1L;
}
