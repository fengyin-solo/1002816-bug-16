import { defineStore } from 'pinia'

export const OPERATOR_ROLES = ['填报人', '组长', '只读岗']
export const OPERATOR_GROUPS = ['一班', '二班', '三班']

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '值班管理员',
    role: '填报人',
    group: '一班',
    shiftLabel: '白班 08:00-20:00',
    scope: '园林绿化养护管理平台',
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
    isLeader: (state) => state.role === '组长',
    isReadonly: (state) => state.role === '只读岗',
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    setRole(role: string) {
      this.role = role
    },
    setGroup(group: string) {
      this.group = group
    },
  },
})
