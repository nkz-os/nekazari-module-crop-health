import { useAuth } from '@nekazari/sdk';

/**
 * True when the user holds one of the roles vegetation lets activate. When the roles of the
 * user or of the module are unknown the answer is true: the core's 403 is explained instead.
 */
export function canActivate(userRoles: string[], activationRoles: string[]): boolean {
  if (userRoles.length === 0 || activationRoles.length === 0) return true;
  return activationRoles.some((r) => userRoles.includes(r));
}

export function useCanActivateMonitoring(activationRoles: string[]): boolean {
  const { user } = useAuth();
  return canActivate(user?.roles ?? [], activationRoles);
}
