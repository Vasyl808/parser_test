import { create } from 'zustand'

const FALLBACK_VOICES = [
  { short_name: 'uk-UA-PolinaNeural', display_name: 'Поліна' },
  { short_name: 'uk-UA-OstapNeural', display_name: 'Остап' }
]

const API_BASE = import.meta.env.VITE_API_URL || ''

export const useStore = create((set, get) => ({
  // App State
  activeTab: 'chat',
  setActiveTab: (tab) => set({ activeTab: tab }),

  // Data
  stores: [],
  voices: FALLBACK_VOICES,
  selectedVoice: 'uk-UA-PolinaNeural',
  setSelectedVoice: (voice) => set({ selectedVoice: voice }),
  status: 'Готовий',
  setStatus: (status) => set({ status }),

  // Promos State
  promos: [],
  isPromosLoading: false,
  hasMorePromos: true,
  promoOffset: 0,
  
  // Filters
  filters: {
    searchQuery: '',
    store: '',
    minPrice: '',
    maxPrice: '',
    category: '',
    sortBy: ''
  },
  
  setFilters: (newFilters) => set((state) => ({
    filters: { ...state.filters, ...newFilters },
    // Reset offset when filters change
    promoOffset: 0,
    hasMorePromos: true
  })),

  fetchStoresAndVoices: async () => {
    try {
      const [storesRes, voicesRes] = await Promise.all([
        fetch(API_BASE + '/stores'),
        fetch(API_BASE + '/voice/voices')
      ])
      const stores = await storesRes.json()
      const voices = await voicesRes.json()
      set({ stores: stores || [] })
      if (voices && voices.length > 0) {
        set({ voices })
      }
    } catch (err) {
      console.error('Failed to load initial data:', err)
    }
  },

  fetchPromos: async (offset = 0) => {
    const { filters, isPromosLoading } = get()
    if (isPromosLoading) return
    
    set({ isPromosLoading: true })
    
    try {
      const params = new URLSearchParams()
      params.append('limit', '100')
      params.append('offset', offset.toString())
      
      if (filters.searchQuery) params.append('q', filters.searchQuery)
      if (filters.store) params.append('store', filters.store)
      if (filters.minPrice) params.append('min_price', filters.minPrice)
      if (filters.maxPrice) params.append('max_price', filters.maxPrice)
      if (filters.category) params.append('category', filters.category)
      if (filters.sortBy) params.append('sort_by', filters.sortBy)

      const url = `${API_BASE}/products/promos?${params.toString()}`
      const res = await fetch(url)
      const newPromos = await res.json() || []

      set((state) => ({
        promos: offset === 0 ? newPromos : [...state.promos, ...newPromos],
        hasMorePromos: newPromos.length === 100,
        promoOffset: offset,
        isPromosLoading: false
      }))
    } catch (err) {
      console.error('Failed to load promos:', err)
      set({ isPromosLoading: false })
    }
  },

  loadMorePromos: () => {
    const { promoOffset, fetchPromos } = get()
    fetchPromos(promoOffset + 100)
  },

  // Chat State
  messages: [],
  isProcessing: false,
  
  addMessage: (msg) => set((state) => ({ messages: [...state.messages, msg] })),
  setIsProcessing: (isProcessing) => set({ isProcessing }),

  sendMessage: async (text, fromVoice = false, playVoiceCallback) => {
    const { addMessage, setStatus, setIsProcessing } = get()
    if (!text.trim() || get().isProcessing) return

    const userMsg = { id: Date.now(), sender: 'user', text }
    addMessage(userMsg)
    setStatus('Шукаю відповідь...')
    setIsProcessing(true)

    try {
      const chatRes = await fetch(API_BASE + '/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, limit: 100, use_llm: true })
      })
      
      if (!chatRes.ok) throw new Error('API Error')
      
      const chatData = await chatRes.json()
      
      const agentMsg = {
        id: Date.now() + 1,
        sender: 'agent',
        text: chatData.answer,
        products: chatData.products
      }
      addMessage(agentMsg)

      if (fromVoice && playVoiceCallback) {
        await playVoiceCallback(chatData.answer)
      } else {
        setStatus('Готовий')
        setIsProcessing(false)
      }
    } catch (err) {
      console.error(err)
      setStatus('Виникла помилка під час обробки.')
      setIsProcessing(false)
    }
  }
}))
