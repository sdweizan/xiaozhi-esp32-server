import { getServiceUrl } from '../api';
import RequestService from '../httpRequest';

export default {
    // 已绑设备
    getAgentBindDevices(agentId, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/device/bind/${agentId}`)
            .method('GET')
            .success((res) => {
                RequestService.clearRequestTime();
                callback(res);
            })
            .networkFail((err) => {
                console.error('获取设备列表失败:', err);
                RequestService.reAjaxFun(() => {
                    this.getAgentBindDevices(agentId, callback);
                });
            }).send();
    },
    // 解绑设备
    unbindDevice(device_id, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/device/unbind`)
            .method('POST')
            .data({ deviceId: device_id })
            .success((res) => {
                RequestService.clearRequestTime();
                callback(res);
            })
            .networkFail((err) => {
                console.error('解绑设备失败:', err);
                RequestService.reAjaxFun(() => {
                    this.unbindDevice(device_id, callback);
                });
            }).send();
    },
    // 绑定设备
    bindDevice(agentId, deviceCode, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/device/bind/${agentId}/${deviceCode}`)
            .method('POST')
            .success((res) => {
                RequestService.clearRequestTime();
                callback(res);
            })
            .networkFail((err) => {
                console.error('绑定设备失败:', err);
                RequestService.reAjaxFun(() => {
                    this.bindDevice(agentId, deviceCode, callback);
                });
            }).send();
    },
    updateDeviceInfo(id, payload, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/device/update/${id}`)
            .method('PUT')
            .data(payload)
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res)
            })
            .networkFail((err) => {
                console.error('更新OTA状态失败:', err)
                this.$message.error(err.msg || '更新OTA状态失败')
                RequestService.reAjaxFun(() => {
                    this.updateDeviceInfo(id, payload, callback)
                })
            }).send()
    },
    // 手动添加设备
    manualAddDevice(params, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/device/manual-add`)
            .method('POST')
            .data(params)
            .success((res) => {
                RequestService.clearRequestTime();
                callback(res);
            })
            .networkFail((err) => {
                console.error('手动添加设备失败:', err);
                RequestService.reAjaxFun(() => {
                    this.manualAddDevice(params, callback);
                });
            }).send();
    },
    // 获取设备状态
    getDeviceStatus(agentId, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/device/bind/${agentId}`)
            .method('POST')
            .data({}) // 发送空对象作为请求体
            .success((res) => {
                RequestService.clearRequestTime();
                callback(res);
            })
            .fail((res) => {
                callback(res);
            })
            .networkFail((err) => {
                console.error('获取设备状态失败:', err);
                RequestService.reAjaxFun(() => {
                    this.getDeviceStatus(agentId, callback);
                });
            }).send();
    },
    // 获取可绑定的固件列表
    getOtaOptions(callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/device/ota/options`)
            .method('GET')
            .success((res) => {
                RequestService.clearRequestTime();
                callback(res);
            })
            .networkFail((err) => {
                console.error('获取可绑定固件列表失败:', err);
                callback({ data: { code: -1, msg: '获取可绑定固件列表失败' } });
            }).send();
    },
    // 设置设备定向固件(otaId 为空表示清除绑定，恢复按型号自动升级)
    setDeviceOta(id, otaId, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/device/ota/${id}`)
            .method('PUT')
            .data({ otaId: otaId || null })
            .success((res) => {
                RequestService.clearRequestTime();
                callback(res);
            })
            .networkFail((err) => {
                console.error('设置设备定向固件失败:', err);
                callback({ data: { code: -1, msg: '设置设备定向固件失败' } });
            }).send();
    },
}