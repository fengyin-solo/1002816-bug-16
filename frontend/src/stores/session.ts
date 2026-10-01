import { defineStore } from 'pinia'

export type OperatorRole = '填报人' | '组长' | '只读'

export const OPERATOR_ROLES: OperatorRole[] = ['填报人', '组长', '只读']
export const WORK_GROUPS = ['绿化一组', '绿化二组', '绿化三组']

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '值班管理员',
    role: '填报人' as OperatorRole,
    group: '绿化一组',
    shiftLabel: '白班 08:00-20:00',
    scope: '园林绿化养护管理平台',
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
    isReadonly: (state) => state.role === '只读',
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
  },
})
