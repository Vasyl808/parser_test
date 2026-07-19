import { useEffect, useRef, useState } from 'react'
import { useStore } from './store'
import './App.css'

const API_BASE = import.meta.env.VITE_API_URL || ''

export default function App() {
  const {
    activeTab, setActiveTab,
    stores, voices, selectedVoice, setSelectedVoice,
    status, setStatus,
    promos, isPromosLoading, hasMorePromos,
    filters, setFilters, fetchPromos, loadMorePromos, fetchStoresAndVoices,
    messages, isProcessing, sendMessage
  } = useStore()

  const [isRecording, setIsRecording] = useState(false)
  const [interimText, setInterimText] = useState('')
  const [inputText, setInputText] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  
  const recognitionRef = useRef(null)
  const audioRef = useRef(null)
  const chatEndRef = useRef(null)

  useEffect(() => {
    fetchStoresAndVoices()
  }, [])

  useEffect(() => {
    if (activeTab === 'chat') {
      chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, interimText, isProcessing, status, activeTab])

  // Fetch promos when filters change or tab changes
  useEffect(() => {
    if (activeTab === 'promos') {
      fetchPromos(0)
    }
  }, [activeTab, filters.store, filters.searchQuery, filters.minPrice, filters.maxPrice, filters.category, filters.sortBy])

  const playVoice = async (text) => {
    if (!text) return
    setStatus('Генерую голос...')
    useStore.getState().setIsProcessing(true)
    try {
      const synthRes = await fetch(API_BASE + '/voice/synthesize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice: selectedVoice, rate: '+18%' })
      })

      if (!synthRes.ok) throw new Error('TTS Error')
      
      if (useStore.getState().status !== 'Генерую голос...') return;

      const audioBlob = await synthRes.blob()
      const audioUrl = URL.createObjectURL(audioBlob)
      
      if (audioRef.current) audioRef.current.pause()
      
      const audio = new Audio(audioUrl)
      audioRef.current = audio
      audio.play()
      
      audio.onended = () => {
        setStatus('Готовий')
        useStore.getState().setIsProcessing(false)
      }
      setStatus('Відповідаю...')
    } catch (err) {
       console.error("TTS failed", err)
       setStatus('Готовий')
       useStore.getState().setIsProcessing(false)
    }
  }

  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognition) {
      setStatus('Ваш браузер не підтримує розпізнавання голосу.')
      return
    }

    const recognition = new SpeechRecognition()
    recognition.lang = 'uk-UA'
    recognition.continuous = false
    recognition.interimResults = true

    recognition.onstart = () => {
      setIsRecording(true)
      setStatus('Уважно слухаю...')
      setInterimText('')
      if (audioRef.current) audioRef.current.pause()
    }

    recognition.onresult = (event) => {
      let finalTranscript = ''
      let interimTranscript = ''
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) finalTranscript += event.results[i][0].transcript
        else interimTranscript += event.results[i][0].transcript
      }
      setInterimText(interimTranscript)
      if (finalTranscript) {
        sendMessage(finalTranscript, true, playVoice)
      }
    }

    recognition.onerror = (event) => {
      console.error('Speech recognition error', event.error)
      setIsRecording(false)
      setStatus('Помилка: ' + event.error)
      setInterimText('')
    }

    recognition.onend = () => {
      setIsRecording(false)
      setStatus(prev => prev === 'Уважно слухаю...' ? 'Готовий' : prev)
      setInterimText('')
    }
    recognitionRef.current = recognition
  }, [status, selectedVoice])

  const stopVoice = () => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.currentTime = 0
    }
    setStatus('Готовий')
    useStore.getState().setIsProcessing(false)
  }

  const toggleRecording = async () => {
    if (isProcessing) return
    if (!recognitionRef.current) return
    if (isRecording) {
      recognitionRef.current.stop()
    } else {
      try {
        if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
          // Explicitly ask for mic permission to trigger the browser prompt on mobile
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          // We don't need to keep the stream for SpeechRecognition, so we can stop its tracks immediately
          stream.getTracks().forEach(track => track.stop());
        }
        recognitionRef.current.start()
      } catch (err) {
        console.error("Could not start recognition or mic permission denied", err)
        setStatus('Помилка доступу до мікрофона.')
      }
    }
  }

  const submitText = (e) => {
    e.preventDefault()
    if (isProcessing) return
    if (inputText.trim()) {
      sendMessage(inputText, false)
      setInputText('')
    }
  }

  const handleFilterChange = (e) => {
    const { name, value } = e.target
    setFilters({ [name]: value })
  }

  return (
    <div className="app-container">
      <header className="header">
        <div className="header-title">
          <div className="logo-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="9" cy="21" r="1"></circle><circle cx="20" cy="21" r="1"></circle>
              <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"></path>
            </svg>
          </div>
          Розумний Кошик
        </div>
        
        <div className="header-tabs">
          <button 
            className={`tab-button ${activeTab === 'chat' ? 'active' : ''}`}
            onClick={() => setActiveTab('chat')}
          >
            💬 Чат
          </button>
          <button 
            className={`tab-button ${activeTab === 'promos' ? 'active' : ''}`}
            onClick={() => setActiveTab('promos')}
          >
            🔥 Акції
          </button>
        </div>

        <div className="header-controls">
          <div className="voice-select-wrapper">
            <select 
              className="voice-select"
              value={selectedVoice}
              onChange={(e) => setSelectedVoice(e.target.value)}
              disabled={isProcessing}
            >
              {voices.map(v => (
                <option key={v.short_name} value={v.short_name}>
                  {v.display_name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </header>

      {activeTab === 'chat' ? (
        <>
          <main className="chat-main">
            <div className="chat-content">
              {messages.length === 0 && !interimText && !isProcessing && (
                <div className="welcome-state">
                  <div className="welcome-title">Привіт! Я твій помічник з покупок.</div>
                  <div className="welcome-subtitle">
                    Я знаю актуальні ціни та акції в супермаркетах. Напиши або скажи:
                  </div>
                  <div className="suggestions">
                    <button className="suggestion-pill" onClick={() => sendMessage("Де зараз дешеве молоко?", false)}>
                      🥛 Де зараз дешеве молоко?
                    </button>
                    <button className="suggestion-pill" onClick={() => sendMessage("Які знижки на каву?", false)}>
                      ☕ Які знижки на каву?
                    </button>
                    <button className="suggestion-pill" onClick={() => sendMessage("Покажи найдешевші яйця", false)}>
                      🥚 Покажи найдешевші яйця
                    </button>
                  </div>
                </div>
              )}

              {messages.map(msg => (
                <div key={msg.id} className={`message-row ${msg.sender}`}>
                  {msg.sender === 'agent' && (
                    <div className="avatar">
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path>
                        <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
                      </svg>
                    </div>
                  )}
                  
                  <div className="message-content">
                    <div className="message-bubble" style={msg.sender === 'agent' ? { whiteSpace: 'pre-wrap' } : undefined}>
                      {msg.text}
                      {msg.sender === 'agent' && (
                        <button 
                           className="play-tts-button" 
                           onClick={() => playVoice(msg.text)}
                           title="Прослухати"
                           disabled={isProcessing}
                        >
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon>
                            <path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path>
                            <path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path>
                          </svg>
                        </button>
                      )}
                    </div>
                    
                    {msg.products && msg.products.length > 0 && (
                      <div className="products-wrapper">
                        <div className="products-grid">
                          {msg.products.map(p => (
                            <div key={p.store_product_id} className="product-card">
                              {p.image_url && (
                                <div className="product-image-container">
                                  <img src={p.image_url} alt={p.name} className="product-image" loading="lazy" />
                                </div>
                              )}
                              <div className="product-title">{p.name}</div>
                              <div className="product-price-row">
                                {p.current_price && <span className="current-price">{p.current_price.toFixed(2)} ₴</span>}
                                {p.regular_price && p.regular_price !== p.current_price && (
                                  <span className="regular-price">{p.regular_price.toFixed(2)} ₴</span>
                                )}
                              </div>
                              <div className="product-meta">
                                {p.discount && <span className="badge promo">-{p.discount}%</span>}
                                {p.is_economy && <span className="badge promo">Ціна тижня</span>}
                                {p.price_per_unit && p.normalized_unit && (
                                  <span className="badge ppu">
                                    {p.price_per_unit.toFixed(2)} ₴/{p.normalized_unit === 'kg' ? 'кг' : p.normalized_unit === 'l' ? 'л' : 'шт'}
                                  </span>
                                )}
                                <span className="badge store">{p.store}</span>
                              </div>
                              {p.url && (
                                <a href={p.url} target="_blank" rel="noopener noreferrer" className="product-link">
                                  🛒 Купити
                                </a>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ))}
              
              {interimText && (
                <div className="message-row user">
                  <div className="message-content">
                    <div className="message-bubble interim-bubble">
                      {interimText}
                    </div>
                  </div>
                </div>
              )}

              {isProcessing && !interimText && (status === 'Шукаю відповідь...' || status === 'Генерую голос...') && (
                <div className="message-row agent">
                  <div className="avatar">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path>
                      <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
                    </svg>
                  </div>
                  <div className="message-content">
                    <div className="message-bubble loading-bubble">
                      <div className="loading-dots">
                        <span className="dot"></span>
                        <span className="dot"></span>
                        <span className="dot"></span>
                      </div>
                      <span className="loading-label">
                        {status === 'Генерую голос...' ? 'Генерую голос...' : 'Шукаю відповідь...'}
                      </span>
                    </div>
                  </div>
                </div>
              )}
              
              <div ref={chatEndRef} />
            </div>
          </main>

          <footer className="input-footer">
            <form className="input-container" onSubmit={submitText}>
              {isRecording && (
                <div className="recording-indicator">
                  <div className="recording-status">
                    <div className="recording-dot"></div>
                    Уважно слухаю...
                  </div>
                  <button 
                    type="button"
                    className="cancel-record-button"
                    onClick={toggleRecording}
                  >
                    Зупинити
                  </button>
                </div>
              )}

              <input
                type="text"
                className="text-input"
                placeholder={isProcessing ? status : 'Запитайте про товари...'}
                value={inputText}
                onChange={e => setInputText(e.target.value)}
                disabled={isRecording || isProcessing}
              />
              
              <div className="input-actions">
                {inputText.trim() ? (
                  <button type="submit" className="icon-button send-button" aria-label="Надіслати" disabled={isProcessing}>
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="22" y1="2" x2="11" y2="13"></line>
                      <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                    </svg>
                  </button>
                ) : (status === 'Відповідаю...' || status === 'Генерую голос...') ? (
                  <button 
                    type="button"
                    className="icon-button stop-button"
                    onClick={stopVoice}
                    aria-label="Зупинити озвучення"
                    title="Зупинити озвучення"
                    style={{ color: '#ff4d4f' }}
                  >
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="6" y="6" width="12" height="12"></rect>
                    </svg>
                  </button>
                ) : (
                  <button 
                    type="button"
                    className={`icon-button mic-button-small ${isRecording ? 'active' : ''}`}
                    onClick={toggleRecording}
                    aria-label="Голосовий ввід"
                    disabled={isProcessing}
                    style={{ opacity: isProcessing ? 0.5 : 1 }}
                  >
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path>
                      <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
                      <line x1="12" y1="19" x2="12" y2="22"></line>
                    </svg>
                  </button>
                )}
              </div>
            </form>
          </footer>
        </>
      ) : (
        <main className="promos-main">
          <div className="promos-container">
            <div className="promos-header-row">
              <div className="search-bar">
                <svg className="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="11" cy="11" r="8"></circle>
                  <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                </svg>
                <input 
                  type="text" 
                  name="searchQuery"
                  placeholder="Пошук акційних товарів..." 
                  value={filters.searchQuery}
                  onChange={(e) => setFilters({ searchQuery: e.target.value })}
                />
              </div>
              <button 
                className={`filter-toggle-btn ${showFilters ? 'active' : ''}`}
                onClick={() => setShowFilters(!showFilters)}
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon>
                </svg>
                Фільтри
              </button>
            </div>

            {showFilters && (
              <div className="filters-panel">
                <div className="filter-group">
                  <label>Магазин</label>
                  <div className="store-filters">
                    <button 
                      className={`store-pill ${filters.store === '' ? 'active' : ''}`}
                      onClick={() => setFilters({ store: '' })}
                    >
                      Всі
                    </button>
                    {stores.map(store => (
                      <button 
                        key={store.id}
                        className={`store-pill ${filters.store === store.slug ? 'active' : ''}`}
                        onClick={() => setFilters({ store: store.slug })}
                      >
                        {store.name}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="filter-group row-group">
                  <div className="filter-item">
                    <label>Ціна від (₴)</label>
                    <input 
                      type="number" 
                      name="minPrice" 
                      value={filters.minPrice} 
                      onChange={handleFilterChange} 
                      placeholder="0"
                      min="0"
                    />
                  </div>
                  <div className="filter-item">
                    <label>Ціна до (₴)</label>
                    <input 
                      type="number" 
                      name="maxPrice" 
                      value={filters.maxPrice} 
                      onChange={handleFilterChange} 
                      placeholder="Напр. 20000"
                      min="0"
                    />
                  </div>
                </div>

                <div className="filter-group row-group">
                  <div className="filter-item">
                    <label>Сортування</label>
                    <select name="sortBy" value={filters.sortBy} onChange={handleFilterChange}>
                      <option value="">Найбільша знижка</option>
                      <option value="price_asc">Від найдешевших</option>
                      <option value="price_desc">Від найдорожчих</option>
                    </select>
                  </div>
                  <div className="filter-item">
                    <label>Категорія (пошук)</label>
                    <input 
                      type="text" 
                      name="category" 
                      value={filters.category} 
                      onChange={handleFilterChange} 
                      placeholder="Напр. м'ясо"
                    />
                  </div>
                </div>
              </div>
            )}
            
            <div className="promos-content">
            {isPromosLoading && promos.length === 0 ? (
              <div className="promos-loading">Завантаження акцій...</div>
            ) : promos.length === 0 ? (
              <div className="promos-empty">Акційних товарів не знайдено за такими критеріями.</div>
            ) : (
              <>
                <div className="products-grid promos-grid">
                  {promos.map(p => (
                    <div key={p.store_product_id} className="product-card">
                      {p.image_url && (
                        <div className="product-image-container">
                          <img src={p.image_url} alt={p.name} className="product-image" loading="lazy" />
                        </div>
                      )}
                      <div className="product-title">{p.name}</div>
                      <div className="product-price-row">
                        {p.current_price && <span className="current-price">{p.current_price.toFixed(2)} ₴</span>}
                        {p.regular_price && p.regular_price !== p.current_price && (
                          <span className="regular-price">{p.regular_price.toFixed(2)} ₴</span>
                        )}
                      </div>
                      <div className="product-meta">
                        {p.discount && <span className="badge promo">-{p.discount}%</span>}
                        {p.is_economy && <span className="badge promo">Ціна тижня</span>}
                        {p.price_per_unit && p.normalized_unit && (
                          <span className="badge ppu">
                            {p.price_per_unit.toFixed(2)} ₴/{p.normalized_unit === 'kg' ? 'кг' : p.normalized_unit === 'l' ? 'л' : 'шт'}
                          </span>
                        )}
                        <span className="badge store">{p.store}</span>
                      </div>
                      {p.url && (
                        <a href={p.url} target="_blank" rel="noopener noreferrer" className="product-link">
                          🛒 Купити
                        </a>
                      )}
                    </div>
                  ))}
                </div>
                {hasMorePromos && (
                  <div className="load-more-container" style={{ textAlign: 'center', marginTop: '20px' }}>
                    <button 
                      className="load-more-btn store-pill" 
                      onClick={loadMorePromos}
                      disabled={isPromosLoading}
                      style={{ cursor: isPromosLoading ? 'wait' : 'pointer' }}
                    >
                      {isPromosLoading ? 'Завантаження...' : 'Завантажити ще'}
                    </button>
                  </div>
                )}
              </>
            )}
            </div>
          </div>
        </main>
      )}
    </div>
  )
}
