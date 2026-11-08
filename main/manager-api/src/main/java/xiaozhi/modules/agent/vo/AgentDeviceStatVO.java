package xiaozhi.modules.agent.vo;

import java.util.Date;

import lombok.Data;

/**
 * 智能体的设备统计信息（列表页批量查询用）
 */
@Data
public class AgentDeviceStatVO {

    /** 智能体ID */
    private String agentId;

    /** 绑定的设备数量 */
    private Integer deviceCount;

    /** 最近一次设备连接时间 */
    private Date lastConnectedAt;
}
