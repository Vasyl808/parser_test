import { useState, useEffect, useRef } from 'react'
import './App.css'

const FALLBACK_VOICES = [
  { short_name: 'uk-UA-PolinaNeural', display_name: 'Поліна' },
  { short_name: 'uk-UA-OstapNeural', display_name: 'Остап' }
]

export default function App() {
  const [activeTab, setActiveTab] = useState('chat') // 'chat' or 'promos'
  const [stores, setStores] = useState([])
  const [selectedStore, setSelectedStore] = useState('')
  const [promos, setPromos] = useState([])
  const [isPromosLoading, setIsPromosLoading] = useState(false)
  const [promoOffset, setPromoOffset] = useState(0)
  const [hasMorePromos, setHasMorePromos] = useState(true)

  const [messages, setMessages] = useState([])
  const [isRecording, setIsRecording] = useState(false)
  const [interimText, setInterimText] = useState('')
  const [inputText, setInputText] = useState('')
  const [status, setStatus] = useState('Готовий')
  const [voices, setVoices] = useState(FALLBACK_VOICES)
  const [selectedVoice, setSelectedVoice] = useState('uk-UA-PolinaNeural')
  const [isProcessing, setIsProcessing] = useState(false)
  
  const recognitionRef = useRef(null)
  const audioRef = useRef(null)
  const chatEndRef = useRef(null)

  useEffect(() => {
    if (activeTab === 'chat') {
      chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, interimText, isProcessing, status, activeTab])

  // Fetch voices and stores on mount
  useEffect(() => {
    fetch('/voice/voices')
      .then(res => res.json())
      .then(data => {
        if (data && data.length > 0) {
          setVoices(data)
        }
      })
      .catch(err => console.error('Failed to load voices:', err))

    fetch('/stores')
      .then(res => res.json())
      .then(data => setStores(data || []))
      .catch(err => console.error('Failed to load stores:', err))
  }, [])

  const fetchPromos = (offset = 0) => {
    setIsPromosLoading(true)
    const url = selectedStore 
      ? `/products/promos?store=${selectedStore}&limit=100&offset=${offset}`
      : `/products/promos?limit=100&offset=${offset}`
      
    fetch(url)
      .then(res => res.json())
      .then(data => {
        const newPromos = data || []
        if (offset === 0) {
          setPromos(newPromos)
        } else {
          setPromos(prev => [...prev, ...newPromos])
        }
        setHasMorePromos(newPromos.length === 100)
        setIsPromosLoading(false)
      })
      .catch(err => {
        console.error('Failed to load promos:', err)
        setIsPromosLoading(false)
      })
  }

  // Fetch promos when tab is active or store changes
  useEffect(() => {
    if (activeTab === 'promos') {
      setPromoOffset(0)
      fetchPromos(0)
    }
  }, [activeTab, selectedStore])

  const loadMorePromos = () => {
    if (isPromosLoading) return
    const nextOffset = promoOffset + 100
    setPromoOffset(nextOffset)
    fetchPromos(nextOffset)
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
      if (audioRef.current) {
        audioRef.current.pause()
      }
    }

    recognition.onresult = (event) => {
      let finalTranscript = ''
      let interimTranscript = ''

      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          finalTranscript += event.results[i][0].transcript
        } else {
          interimTranscript += event.results[i][0].transcript
        }
      }

      setInterimText(interimTranscript)
      
      if (finalTranscript) {
        handleUserMessage(finalTranscript, true)
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
  }, [status])

  const toggleRecording = () => {
    if (isProcessing) return
    if (!recognitionRef.current) return

    if (isRecording) {
      recognitionRef.current.stop()
    } else {
      try {
        recognitionRef.current.start()
      } catch (err) {
        console.error("Could not start recognition", err)
      }
    }
  }

  const submitText = (e) => {
    e.preventDefault()
    if (isProcessing) return
    if (inputText.trim()) {
      handleUserMessage(inputText, false)
      setInputText('')
    }
  }

  const handleUserMessage = async (text, fromVoice = false) => {
    if (!text.trim() || isProcessing) return

    const userMsg = { id: Date.now(), sender: 'user', text }
    setMessages(prev => [...prev, userMsg])
    setStatus('Шукаю відповідь...')
    setIsProcessing(true)

    try {
      const chatRes = await fetch('/chat', {
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
      setMessages(prev => [...prev, agentMsg])

      if (fromVoice) {
        await playVoice(chatData.answer)
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

  const playVoice = async (text) => {
    if (!text) return
    
    setStatus('Генерую голос...')
    setIsProcessing(true)
    
    try {
      const synthRes = await fetch('/voice/synthesize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice: selectedVoice, rate: '+18%' })
      })

      if (!synthRes.ok) throw new Error('TTS Error')

      const audioBlob = await synthRes.blob()
      const audioUrl = URL.createObjectURL(audioBlob)
      
      if (audioRef.current) {
        audioRef.current.pause()
      }
      
      const audio = new Audio(audioUrl)
      audioRef.current = audio
      audio.play()
      
      audio.onended = () => {
        setStatus('Готовий')
        setIsProcessing(false)
      }
      
      setStatus('Відповідаю...')
    } catch (err) {
       console.error("TTS failed", err)
       setStatus('Готовий')
       setIsProcessing(false)
    }
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
                    <button className="suggestion-pill" onClick={() => handleUserMessage("Де зараз дешеве молоко?", false)}>
                      🥛 Де зараз дешеве молоко?
                    </button>
                    <button className="suggestion-pill" onClick={() => handleUserMessage("Які знижки на каву?", false)}>
                      ☕ Які знижки на каву?
                    </button>
                    <button className="suggestion-pill" onClick={() => handleUserMessage("Покажи найдешевші яйця", false)}>
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
            <div className="store-filters">
              <button 
                className={`store-pill ${selectedStore === '' ? 'active' : ''}`}
                onClick={() => setSelectedStore('')}
              >
                Всі магазини
              </button>
              {stores.map(store => (
                <button 
                  key={store.id}
                  className={`store-pill ${selectedStore === store.slug ? 'active' : ''}`}
                  onClick={() => setSelectedStore(store.slug)}
                >
                  {store.name}
                </button>
              ))}
            </div>
            
            <div className="promos-content">
            {isPromosLoading && promos.length === 0 ? (
              <div className="promos-loading">Завантаження акцій...</div>
            ) : promos.length === 0 ? (
              <div className="promos-empty">Акційних товарів не знайдено.</div>
            ) : (
              <>
                <div className="products-grid promos-grid">
                  {promos.map(p => (
                    <div key={p.store_product_id} className="product-card">
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
