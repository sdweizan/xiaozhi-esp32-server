package xiaozhi.modules.agent.dao;

import java.util.List;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import org.apache.ibatis.annotations.Select;
import xiaozhi.common.dao.BaseDao;
import xiaozhi.modules.agent.entity.AgentEntity;
import xiaozhi.modules.agent.vo.AgentDeviceStatVO;
import xiaozhi.modules.agent.vo.AgentInfoVO;

@Mapper
public interface AgentDao extends BaseDao<AgentEntity> {
    /**
     * 获取智能体的设备数量
     * 
     * @param agentId 智能体ID
     * @return 设备数量
     */
    Integer getDeviceCountByAgentId(@Param("agentId") String agentId);

    /**
     * 批量获取智能体的设备数量与最近连接时间，避免列表页逐条查询
     *
     * @param agentIds 智能体ID列表（调用方需保证非空，且按批控制长度）
     * @return 每个智能体一条统计（无设备的智能体不会出现在结果中）
     */
    List<AgentDeviceStatVO> getDeviceStatsByAgentIds(@Param("agentIds") List<String> agentIds);

    /**
     * 根据设备MAC地址查询对应设备的默认智能体信息
     *
     * @param macAddress 设备MAC地址
     * @return 默认智能体信息
     */
    @Select(" SELECT a.* FROM ai_device d " +
            " LEFT JOIN ai_agent a ON d.agent_id = a.id " +
            " WHERE d.mac_address = #{macAddress} " +
            " ORDER BY d.id DESC LIMIT 1")
    AgentEntity getDefaultAgentByMacAddress(@Param("macAddress") String macAddress);

    /**
     * 根据id查询agent信息，包括插件信息
     *
     * @param agentId 智能体ID
     */
    AgentInfoVO selectAgentInfoById(@Param("agentId") String agentId);
}
