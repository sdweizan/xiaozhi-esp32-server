package xiaozhi.modules.security.system;

import jakarta.annotation.Resource;
import org.apache.shiro.authc.AuthenticationException;
import org.apache.shiro.authc.AuthenticationInfo;
import org.apache.shiro.authc.AuthenticationToken;
import org.apache.shiro.authc.SimpleAuthenticationInfo;
import org.apache.shiro.authz.AuthorizationInfo;
import org.apache.shiro.authz.SimpleAuthorizationInfo;
import org.apache.shiro.realm.AuthorizingRealm;
import org.apache.shiro.subject.PrincipalCollection;
import org.springframework.context.annotation.Lazy;
import org.springframework.stereotype.Component;
import xiaozhi.common.user.UserDetail;
import xiaozhi.common.utils.ConvertUtils;
import xiaozhi.modules.security.service.ShiroService;
import xiaozhi.modules.sys.dto.SysUserDTO;
import xiaozhi.modules.sys.entity.SysUserEntity;
import xiaozhi.modules.sys.enums.SuperAdminEnum;
import xiaozhi.modules.sys.service.SysUserService;

import java.util.HashSet;
import java.util.Set;

@Component
public class SystemRealm extends AuthorizingRealm {
    @Lazy
    @Resource
    private SysUserService sysUserService;

    @Override
    public boolean supports(AuthenticationToken token) {
        return token instanceof SystemToken;
    }

    @Override
    protected AuthorizationInfo doGetAuthorizationInfo(PrincipalCollection principalCollection) {
        String username = (String) principalCollection.getPrimaryPrincipal();
        SysUserDTO sysUserDTO = sysUserService.getByUsername(username);

        // 用户权限列表
        Set<String> permsSet = new HashSet<>();

        if (sysUserDTO.getSuperAdmin() == SuperAdminEnum.YES.value()) {
            permsSet.add("sys:role:superAdmin");
            permsSet.add("sys:role:normal");
        } else {
            permsSet.add("sys:role:normal");
        }

        SimpleAuthorizationInfo info = new SimpleAuthorizationInfo();
        info.setStringPermissions(permsSet);
        return info;
    }

    @Override
    protected AuthenticationInfo doGetAuthenticationInfo(AuthenticationToken authenticationToken) throws AuthenticationException {
        String username = (String) authenticationToken.getCredentials();
        SysUserDTO sysUserDTO = sysUserService.getByUsername(username);
        UserDetail userDetail = ConvertUtils.sourceToTarget(sysUserDTO, UserDetail.class);
        return new SimpleAuthenticationInfo(userDetail, username, getName());
    }
}
