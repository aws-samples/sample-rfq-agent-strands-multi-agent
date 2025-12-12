import React, { useState, useRef, useEffect } from 'react';
import { signOut, fetchAuthSession } from 'aws-amplify/auth';
import { awsConfig } from './aws-config';

const Chat = ({ user }) => {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [websocket, setWebsocket] = useState(null);
  const messagesEndRef = useRef(null);
  const heartbeatRef = useRef(null);
  const [loadingMessage, setLoadingMessage] = useState('Sending to AI...');
  const loadingMessageRef = useRef(null);
  const [activeTab, setActiveTab] = useState('agent');
  const [files, setFiles] = useState([]);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [conversations, setConversations] = useState([{ id: 1, name: 'General', messages: [] }]);
  const [activeConversation, setActiveConversation] = useState(1);

  const getTwoDaysFromNow = () => {
    const date = new Date();
    date.setDate(date.getDate() + 2);
    return date.toISOString().split('T')[0];
  };

  const sampleQuestions = [
    'Do you have material information for category Brakes ?',
    'Can you list vendor for material MZ-RM-C900-06 from quality ratings ?',
    'Do you have financial information for suppliers of material MZ-RM-C900-06 ?',
    'Can you show all compliance details for vendors USSU-VSF06, EWM17-SU01 and USSU-VSF01 ?',
    'can you analyze and recommend the best vendor for material MZ-RM-C900-06 ?',
    'Can you create a comparison bar chart with vendor for material MZ-RM-C900-06 from quality ratings ?',
    'Can you show a scatter diagram for vendor for material MZ-RM-C900-06 from finance ratings?',
    `Create RFQ for material MZ-RM-C900-06 to vendor USSU-VSF01 with quantity 10 and delivery date ${getTwoDaysFromNow()}`
  ];

  const formatText = (text) => {
    return text
      .split('\n')
      .map((line, index) => {
        // Process bold text **text**
        const parts = [];
        let lastIndex = 0;
        const boldRegex = /\*\*(.*?)\*\*/g;
        let match;
        
        while ((match = boldRegex.exec(line)) !== null) {
          if (match.index > lastIndex) {
            parts.push(line.substring(lastIndex, match.index));
          }
          parts.push(<strong key={`bold-${index}-${match.index}`}>{match[1]}</strong>);
          lastIndex = match.index + match[0].length;
        }
        if (lastIndex < line.length) {
          parts.push(line.substring(lastIndex));
        }
        
        // Handle numbered lists and bullet points
        const processedLine = parts.length > 0 ? parts : line;
        const isNumberedList = /^(\d+\.)\s/.test(line);
        const isBulletPoint = /^-\s/.test(line);
        
        if (isNumberedList) {
          const numMatch = line.match(/^(\d+\.)\s(.*)/);
          return (
            <div key={index} style={{ marginBottom: line.trim() ? '4px' : '8px' }}>
              <strong>{numMatch[1]}</strong> {numMatch[2]}
            </div>
          );
        } else if (isBulletPoint) {
          return (
            <div key={index} style={{ marginBottom: line.trim() ? '4px' : '8px' }}>
              • {line.substring(2)}
            </div>
          );
        }
        
        return (
          <div key={index} style={{ marginBottom: line.trim() ? '4px' : '8px' }}>
            {parts.length > 0 ? parts : (line || '\u00A0')}
          </div>
        );
      });
  };

  const parseVisualizationResponse = (text) => {
    const codeMatch = text.match(/\[CODE_START\]([\s\S]*?)\[CODE_END\]/i);
    const execMatch = text.match(/\[EXEC_START\]([\s\S]*?)\[EXEC_END\]/i);
    const imageMatches = [...text.matchAll(/\[IMAGE\]([^\[]+)\[\/IMAGE\]/gi)];
    
    const hasVisualization = !!(codeMatch || execMatch || imageMatches.length > 0);
    
    let cleanText = text
      .replace(/\[CODE_START\][\s\S]*?\[CODE_END\]/gi, '')
      .replace(/\[EXEC_START\][\s\S]*?\[EXEC_END\]/gi, '')
      .replace(/\[IMAGE\][^\[]+\[\/IMAGE\]/gi, '')
      .trim();
    
    return {
      hasVisualization,
      code: codeMatch ? codeMatch[1].trim() : null,
      execStatus: execMatch ? execMatch[1].trim() : null,
      imageUrls: imageMatches.map(match => match[1].trim()),
      cleanText
    };
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    // Connect to WebSocket with signed URL
    const connectWebSocket = async () => {
      try {
        const session = await fetchAuthSession();
        const accessToken = session.tokens?.accessToken?.toString();
        
        // Append token as query parameter
        const wsUrl = `${awsConfig.API.REST.chatApi.endpoint}?token=${accessToken}`;
        const ws = new WebSocket(wsUrl);
    
        ws.onopen = () => {
          console.log('WebSocket connected');
          setWebsocket(ws);
        };
    
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      // Ignore ping responses
      if (data.action === 'pong') {
        return;
      }
      
      // Handle file list response
      if (data.action === 'files_list') {
        setFiles(data.files || []);
        setLoadingFiles(false);
        return;
      }
      
      // Handle streaming chunks
      if (data.type === 'chunk') {
        setMessages(prev => {
          const newMessages = [...prev];
          const lastMessage = newMessages[newMessages.length - 1];
          
          if (lastMessage && lastMessage.type === 'agent' && lastMessage.streaming) {
            lastMessage.text += data.chunk;
            
            // Extract images from accumulated text (only presigned URLs)
            const imageMatch = lastMessage.text.match(/\[IMAGE\](https?:\/\/[^\[]+)\[\/IMAGE\]/i);
            if (imageMatch && !lastMessage.images.includes(imageMatch[1])) {
              lastMessage.images.push(imageMatch[1]);
            }
          } else {
            const initialImages = [];
            const imageMatch = data.chunk.match(/\[IMAGE\](https?:\/\/[^\[]+)\[\/IMAGE\]/i);
            if (imageMatch) {
              initialImages.push(imageMatch[1]);
            }
            
            newMessages.push({
              text: data.chunk,
              sender: 'Agent',
              timestamp: new Date(),
              type: 'agent',
              streaming: true,
              images: initialImages,
              visualization: null
            });
          }
          return newMessages;
        });
        return;
      }
      
      if (data.type === 'tool_start') {
        setLoadingMessage('Executing code...');
        return;
      }
      
      if (data.type === 'complete') {
        if (heartbeatRef.current) {
          clearInterval(heartbeatRef.current);
          heartbeatRef.current = null;
        }
        if (loadingMessageRef.current) {
          clearInterval(loadingMessageRef.current);
          loadingMessageRef.current = null;
        }
        setLoading(false);
        
        const responseText = data.response || 'No response from agent';
        
        const imageTagRegex = /\[IMAGE\]([^\[]+)\[\/IMAGE\]/gi;
        const imageUrlRegex = /(https?:\/\/[^\s\)\]]+\.(?:jpg|jpeg|png|gif|webp|svg)[^\s\)\]]*)/gi;
        
        const taggedImages = [...responseText.matchAll(imageTagRegex)].map(match => match[1]);
        const rawImageUrls = responseText.match(imageUrlRegex) || [];
        const directImageUrls = rawImageUrls.map(url => url.replace(/&amp;/g, '&').replace(/%29/g, ')'));
        
        const imageUrls = [...new Set([...taggedImages, ...directImageUrls])];
        
        const decodedText = responseText
          .replace(/&#39;/g, "'")
          .replace(/&quot;/g, '"')
          .replace(/&amp;/g, '&')
          .replace(/&lt;/g, '<')
          .replace(/&gt;/g, '>');
        
        const visualization = parseVisualizationResponse(decodedText);
        const finalImageUrls = [...imageUrls, ...(visualization.imageUrls || [])];
        
        setMessages(prev => {
          const newMessages = [...prev];
          const lastMessage = newMessages[newMessages.length - 1];
          
          if (lastMessage && lastMessage.streaming) {
            lastMessage.text = visualization.hasVisualization ? visualization.cleanText : decodedText;
            lastMessage.streaming = false;
            lastMessage.images = [...new Set([...lastMessage.images, ...finalImageUrls])];
            lastMessage.visualization = visualization.hasVisualization ? visualization : null;
          } else {
            newMessages.push({
              text: visualization.hasVisualization ? visualization.cleanText : decodedText,
              sender: 'Agent',
              timestamp: new Date(),
              type: 'agent',
              streaming: false,
              images: [...new Set(finalImageUrls)],
              visualization: visualization.hasVisualization ? visualization : null
            });
          }
          return newMessages;
        });
        return;
      }
      
      // Legacy format and errors
      if (heartbeatRef.current) {
        clearInterval(heartbeatRef.current);
        heartbeatRef.current = null;
      }
      if (loadingMessageRef.current) {
        clearInterval(loadingMessageRef.current);
        loadingMessageRef.current = null;
      }
      setLoading(false);
      
      if (data.error) {
        const errorMessage = {
          text: `Error: ${data.error}`,
          sender: 'System',
          timestamp: new Date(),
          type: 'error'
        };
        setMessages(prev => [...prev, errorMessage]);
      } else if (data.response) {
        const responseText = data.response;
        const imageTagRegex = /\[IMAGE\]([^\[]+)\[\/IMAGE\]/gi;
        const imageUrlRegex = /(https?:\/\/[^\s\)\]]+\.(?:jpg|jpeg|png|gif|webp|svg)[^\s\)\]]*)/gi;
        
        const taggedImages = [...responseText.matchAll(imageTagRegex)].map(match => match[1]);
        const rawImageUrls = responseText.match(imageUrlRegex) || [];
        const directImageUrls = rawImageUrls.map(url => url.replace(/&amp;/g, '&').replace(/%29/g, ')'));
        
        const imageUrls = [...new Set([...taggedImages, ...directImageUrls])];
        
        const decodedText = responseText
          .replace(/&#39;/g, "'")
          .replace(/&quot;/g, '"')
          .replace(/&amp;/g, '&')
          .replace(/&lt;/g, '<')
          .replace(/&gt;/g, '>');
        
        const visualization = parseVisualizationResponse(decodedText);
        const finalImageUrls = [...imageUrls, ...(visualization.imageUrls || [])];
        
        const agentMessage = {
          text: visualization.hasVisualization ? visualization.cleanText : decodedText,
          sender: 'Agent',
          timestamp: new Date(),
          type: 'agent',
          images: finalImageUrls,
          visualization: visualization.hasVisualization ? visualization : null
        };
        setMessages(prev => [...prev, agentMessage]);
      }
    };
    
        ws.onerror = (error) => {
          console.error('WebSocket error:', error);
          setLoading(false);
        };
        
        ws.onclose = () => {
          console.log('WebSocket disconnected');
          setWebsocket(null);
        };
      } catch (error) {
        console.error('Failed to connect WebSocket:', error);
      }
    };
    
    connectWebSocket();
    
    return () => {
      if (heartbeatRef.current) {
        clearInterval(heartbeatRef.current);
      }
      if (loadingMessageRef.current) {
        clearInterval(loadingMessageRef.current);
      }
      if (websocket && websocket.readyState === WebSocket.OPEN) {
        websocket.close();
      }
    };
  }, []);

  const sendMessage = async () => {
    if (input.trim()) {
      const userMessage = { text: input, sender: user.username, timestamp: new Date(), type: 'user' };
      setMessages(prev => [...prev, userMessage]);
      setLoading(true);
      
      try {
        // Get Cognito access token
        const session = await fetchAuthSession();
        const accessToken = session.tokens?.accessToken?.toString();
        
        // Send message via WebSocket
        if (websocket && websocket.readyState === WebSocket.OPEN) {
          setLoading(true);
          setLoadingMessage('Sending to AI...');
          
          // Rotate loading messages to keep user engaged
          const loadingMessages = [
            'Sending to AI...',
            'AI is analyzing...',
            'Processing your request...',
            'Gathering information...',
            'AI is thinking deeply...',
            'Almost there...',
            'Finalizing response...'
          ];
          
          let messageIndex = 0;
          loadingMessageRef.current = setInterval(() => {
            messageIndex = (messageIndex + 1) % loadingMessages.length;
            setLoadingMessage(loadingMessages[messageIndex]);
          }, 4000); // Change message every 4 seconds
          
          // Start heartbeat to keep connection alive
          heartbeatRef.current = setInterval(() => {
            if (websocket.readyState === WebSocket.OPEN) {
              websocket.send(JSON.stringify({
                action: 'ping',
                userId: user.username
              }));
            }
          }, 25000); // Send ping every 25 seconds
          
          websocket.send(JSON.stringify({
            message: input,
            userId: user.username,
            bearerToken: accessToken
          }));
        } else {
          throw new Error('WebSocket not connected');
        }
      } catch (error) {
        console.error('Error calling agent:', error);
        const errorMessage = {
          text: 'Error: Could not reach the agent',
          sender: 'System',
          timestamp: new Date(),
          type: 'error'
        };
        setMessages(prev => [...prev, errorMessage]);
        setLoading(false);
        if (heartbeatRef.current) {
          clearInterval(heartbeatRef.current);
          heartbeatRef.current = null;
        }
        if (loadingMessageRef.current) {
          clearInterval(loadingMessageRef.current);
          loadingMessageRef.current = null;
        }
      }
      
      setInput('');
    }
  };

  const handleSignOut = async () => {
    try {
      await signOut();
    } catch (error) {
      console.log('Error signing out:', error);
    }
  };

  const loadFiles = () => {
    if (websocket && websocket.readyState === WebSocket.OPEN) {
      setLoadingFiles(true);
      websocket.send(JSON.stringify({ action: 'list_files' }));
    }
  };

  const handleQuestionClick = (question) => {
    setInput(question);
    setActiveTab('agent');
  };

  const formatFileSize = (bytes) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const isProcessing = loading || messages.some(msg => msg.streaming);

  return (
    <>
    <div style={{ 
      height: '100vh', 
      display: 'flex',
      fontFamily: 'Calibri, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      backgroundColor: '#fff'
    }}>
      {/* Sidebar */}
      <div style={{
        width: '260px',
        background: 'linear-gradient(180deg, #232F3E 0%, #131A22 100%)',
        color: 'white',
        display: 'flex',
        flexDirection: 'column',
        borderRight: '1px solid rgba(255,255,255,0.1)',
        boxShadow: '4px 0 12px rgba(0,0,0,0.15)',
        borderTopRightRadius: '16px',
        borderBottomRightRadius: '16px'
      }}>
        <div style={{ padding: '20px 16px', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
          <div style={{ 
            display: 'flex', 
            alignItems: 'center', 
            justifyContent: 'space-between',
            marginBottom: '12px'
          }}>
            <h3 style={{ margin: 0, fontSize: '18px', fontWeight: '900' }}>Procurement AI</h3>
            <div style={{ 
              width: '36px', 
              height: '36px', 
              borderRadius: '4px', 
              background: 'linear-gradient(135deg, #FF9900 0%, #FF6600 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '14px',
              fontWeight: '600',
              cursor: 'pointer'
            }}>
              {user.username.charAt(0).toUpperCase()}
            </div>
          </div>
        </div>
        
        <div style={{ padding: '16px 16px 8px' }}>
          <div style={{
            backgroundColor: '#1a1d29',
            border: '1px solid rgba(255,255,255,0.2)',
            borderRadius: '6px',
            padding: '6px 12px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>

            <input
              type="text"
              placeholder="Search"
              style={{
                flex: 1,
                backgroundColor: 'transparent',
                border: 'none',
                color: 'white',
                fontSize: '13px',
                outline: 'none'
              }}
            />
          </div>
        </div>
        
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
          <div style={{ padding: '8px 12px', fontSize: '13px', fontWeight: '600', opacity: 0.7 }}>Channels</div>
          <div 
            onClick={() => setActiveTab('agent')}
            style={{
              padding: '6px 16px',
              margin: '1px 8px',
              cursor: 'pointer',
              background: activeTab === 'agent' ? 'linear-gradient(135deg, #FF9900 0%, #FF6600 100%)' : 'transparent',
              borderRadius: '8px',
              fontSize: '15px',
              fontWeight: activeTab === 'agent' ? '700' : '400',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              boxShadow: activeTab === 'agent' ? '0 2px 8px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.1)' : 'none',
              transition: 'all 0.2s ease'
            }}
            onMouseEnter={(e) => activeTab !== 'agent' && (e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.1)')}
            onMouseLeave={(e) => activeTab !== 'agent' && (e.currentTarget.style.backgroundColor = 'transparent')}
          >
            General
          </div>
          
          <div style={{ padding: '16px 12px 8px', fontSize: '13px', fontWeight: '600', opacity: 0.7 }}>Resources</div>
          <div 
            onClick={() => { setActiveTab('questions'); }}
            style={{
              padding: '6px 16px',
              margin: '1px 8px',
              cursor: 'pointer',
              background: activeTab === 'questions' ? 'linear-gradient(135deg, #FF9900 0%, #FF6600 100%)' : 'transparent',
              borderRadius: '8px',
              fontSize: '15px',
              fontWeight: activeTab === 'questions' ? '700' : '400',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              boxShadow: activeTab === 'questions' ? '0 2px 8px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.1)' : 'none',
              transition: 'all 0.2s ease'
            }}
            onMouseEnter={(e) => activeTab !== 'questions' && (e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.1)')}
            onMouseLeave={(e) => activeTab !== 'questions' && (e.currentTarget.style.backgroundColor = 'transparent')}
          >
            Sample Questions
          </div>
          
          <div 
            onClick={() => { setActiveTab('files'); loadFiles(); }}
            style={{
              padding: '6px 16px',
              margin: '1px 8px',
              cursor: 'pointer',
              background: activeTab === 'files' ? 'linear-gradient(135deg, #FF9900 0%, #FF6600 100%)' : 'transparent',
              borderRadius: '8px',
              fontSize: '15px',
              fontWeight: activeTab === 'files' ? '700' : '400',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              boxShadow: activeTab === 'files' ? '0 2px 8px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.1)' : 'none',
              transition: 'all 0.2s ease'
            }}
            onMouseEnter={(e) => activeTab !== 'files' && (e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.1)')}
            onMouseLeave={(e) => activeTab !== 'files' && (e.currentTarget.style.backgroundColor = 'transparent')}
          >
            Files
          </div>
        </div>
        
        <div style={{ padding: '12px', borderTop: '1px solid rgba(255,255,255,0.1)' }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '8px 12px',
            borderRadius: '6px',
            cursor: 'pointer'
          }}
          onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.1)'}
          onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
          onClick={handleSignOut}>
            <div style={{ 
              width: '32px', 
              height: '32px', 
              borderRadius: '4px', 
              background: 'linear-gradient(135deg, #FF9900 0%, #FF6600 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '14px',
              fontWeight: '600'
            }}>
              {user.username.charAt(0).toUpperCase()}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: '15px', fontWeight: '700' }}>{user.username}</div>
              <div style={{ fontSize: '12px', opacity: 0.7 }}>Sign out</div>
            </div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div style={{ 
        flex: 1,
        display: 'flex', 
        flexDirection: 'column',
        borderTopLeftRadius: '16px',
        borderBottomLeftRadius: '16px',
        overflow: 'hidden',
        boxShadow: '-2px 0 8px rgba(0,0,0,0.08)'
      }}>
        {/* Header */}
        <div style={{ 
          backgroundColor: '#fff', 
          padding: '14px 20px',
          borderBottom: '1px solid #e0e0e0',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          boxShadow: '0 2px 8px rgba(0,0,0,0.06)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <h2 style={{ margin: 0, fontSize: '18px', color: '#1d1c1d', fontWeight: '900' }}>
              {activeTab === 'agent' && 'General'}
              {activeTab === 'questions' && 'Sample Questions'}
              {activeTab === 'files' && 'Files'}
            </h2>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ fontSize: '11px', color: '#616061' }}>
              Powered by <span style={{ fontWeight: '700', color: '#FF9900' }}>Amazon Bedrock</span> <span style={{ fontWeight: '600', color: '#232F3E' }}>Agentcore</span>
            </div>
          </div>
        </div>
        
        {/* Content */}
        {activeTab === 'agent' && (
          <>
            {/* Messages */}
            <div style={{ 
              flex: 1,
              overflowY: 'auto',
              padding: '20px 20px 20px 20px',
              display: 'flex',
              flexDirection: 'column',
              backgroundColor: '#fff'
            }}>
        {messages.length === 0 && (
          <div style={{
            maxWidth: '600px',
            margin: '60px auto',
            textAlign: 'center'
          }}>
            <div style={{
              width: '80px',
              height: '80px',
              background: 'linear-gradient(135deg, #FF9900 0%, #FF6600 100%)',
              borderRadius: '50%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 24px',
              fontSize: '36px',
              color: '#fff',
              fontWeight: '700',
              boxShadow: '0 4px 12px rgba(255,153,0,0.3)'
            }}>AI</div>
            <h3 style={{ color: '#111827', fontSize: '24px', fontWeight: '600', marginBottom: '12px' }}>
              Welcome to RFQ Agent
            </h3>
            <p style={{ color: '#6b7280', fontSize: '16px', lineHeight: '1.6' }}>
              Ask me anything about suppliers, materials, quality ratings, and vendor compliance.
            </p>
          </div>
        )}
        
        {messages.map((msg, index) => (
          <div key={index} style={{ 
            display: 'flex',
            gap: '12px',
            marginBottom: '12px',
            padding: '8px 0'
          }}
          onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#f8f8f8'}
          onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}>
            <div style={{
              width: '36px',
              height: '36px',
              borderRadius: '8px',
              background: msg.type === 'user' ? 'linear-gradient(135deg, #232F3E 0%, #131A22 100%)' : 'linear-gradient(135deg, #FF9900 0%, #FF6600 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '14px',
              fontWeight: '600',
              color: '#fff',
              flexShrink: 0,
              boxShadow: '0 2px 6px rgba(0,0,0,0.15), inset 0 1px 0 rgba(255,255,255,0.2)'
            }}>
              {msg.type === 'user' ? user.username.charAt(0).toUpperCase() : 'AI'}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ 
                fontSize: '15px', 
                fontWeight: '900',
                marginBottom: '4px',
                color: '#1d1c1d',
                display: 'flex',
                alignItems: 'center',
                gap: '8px'
              }}>
                {msg.type === 'user' ? user.username : msg.type === 'error' ? 'System' : 'Procurement AI'}
                <span style={{ fontSize: '12px', fontWeight: '400', color: '#616061' }}>
                  {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
              <div style={{ lineHeight: '1.5', color: '#1d1c1d', fontSize: '15px' }}>
                {msg.type === 'agent' ? formatText(msg.text) : msg.text}
                
                {msg.streaming && (
                  <div style={{ display: 'flex', alignItems: 'center', marginTop: '12px' }}>
                    <div style={{
                      width: '6px',
                      height: '6px',
                      borderRadius: '50%',
                      backgroundColor: '#6b7280',
                      marginRight: '4px',
                      animation: 'pulse 1.5s ease-in-out infinite'
                    }}></div>
                    <div style={{
                      width: '6px',
                      height: '6px',
                      borderRadius: '50%',
                      backgroundColor: '#6b7280',
                      marginRight: '4px',
                      animation: 'pulse 1.5s ease-in-out infinite 0.3s'
                    }}></div>
                    <div style={{
                      width: '6px',
                      height: '6px',
                      borderRadius: '50%',
                      backgroundColor: '#6b7280',
                      animation: 'pulse 1.5s ease-in-out infinite 0.6s'
                    }}></div>
                    <span style={{ marginLeft: '8px', fontSize: '12px', color: '#6b7280', fontStyle: 'italic' }}>Agent is typing...</span>
                  </div>
                )}
                
                {msg.visualization && msg.visualization.code && (
                  <div style={{ marginTop: '12px' }}>
                    <div style={{ fontSize: '12px', fontWeight: 'bold', marginBottom: '4px', color: '#666' }}>Python Code:</div>
                    <pre style={{
                      backgroundColor: '#f5f5f5',
                      padding: '8px',
                      borderRadius: '4px',
                      fontSize: '12px',
                      fontFamily: 'monospace',
                      overflowX: 'auto',
                      margin: 0,
                      whiteSpace: 'pre-wrap'
                    }}>
                      {msg.visualization.code}
                    </pre>
                  </div>
                )}
                
                {msg.visualization && msg.visualization.execStatus && (
                  <div style={{ marginTop: '8px' }}>
                    <div style={{ fontSize: '12px', fontWeight: 'bold', marginBottom: '2px', color: '#666' }}>Execution Status:</div>
                    <div style={{
                      fontSize: '12px',
                      fontWeight: 'bold',
                      color: msg.visualization.execStatus.includes('SUCCESS') ? '#4caf50' : '#f44336'
                    }}>
                      {msg.visualization.execStatus}
                    </div>
                  </div>
                )}
                
                {msg.images && msg.images.length > 0 && (
                  <div style={{ marginTop: '12px' }}>
                    {msg.images.map((imageUrl, imgIndex) => (
                      <img
                        key={imgIndex}
                        src={imageUrl}
                        alt="Agent response image"
                        style={{
                          maxWidth: '100%',
                          height: 'auto',
                          borderRadius: '8px',
                          marginTop: '4px',
                          display: 'block'
                        }}
                        onError={(e) => {
                          e.target.style.display = 'none';
                        }}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
        
        {loading && (
          <div style={{ 
            display: 'flex',
            gap: '12px',
            marginBottom: '12px',
            padding: '8px 0'
          }}>
            <div style={{
              width: '36px',
              height: '36px',
              borderRadius: '4px',
              backgroundColor: '#1164a3',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '14px',
              fontWeight: '600',
              color: '#fff',
              flexShrink: 0
            }}>
              AI
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: '15px', fontWeight: '900', marginBottom: '4px', color: '#1d1c1d' }}>Procurement AI</div>
              <div style={{ display: 'flex', alignItems: 'center' }}>
              <div style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: '#1976d2',
                marginRight: '4px',
                animation: 'pulse 1.5s ease-in-out infinite'
              }}></div>
              <div style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: '#1976d2',
                marginRight: '4px',
                animation: 'pulse 1.5s ease-in-out infinite 0.3s'
              }}></div>
              <div style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: '#1976d2',
                animation: 'pulse 1.5s ease-in-out infinite 0.6s'
              }}></div>
              <span style={{ marginLeft: '8px', color: '#616061', fontSize: '13px', fontStyle: 'italic' }}>{loadingMessage}</span>
            </div>
            </div>
          </div>
        )}
              <div ref={messagesEndRef} />
            </div>
            
            {/* Input */}
            <div style={{ 
              padding: '20px',
              backgroundColor: '#fff',
              borderTop: '1px solid #e0e0e0'
            }}>
              <div style={{ 
                display: 'flex',
                alignItems: 'flex-end',
                gap: '8px',
                border: '1px solid #8d8d8d',
                borderRadius: '12px',
                padding: '8px 12px',
                boxShadow: '0 2px 8px rgba(0,0,0,0.08), inset 0 1px 2px rgba(0,0,0,0.05)'
              }}>
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyPress={(e) => e.key === 'Enter' && !e.shiftKey && !isProcessing && sendMessage()}
                  placeholder="Ask me here..."
                  disabled={isProcessing}
                  style={{ 
                    flex: 1,
                    padding: '8px 4px',
                    border: 'none',
                    fontSize: '15px',
                    outline: 'none',
                    fontFamily: 'inherit',
                    backgroundColor: 'transparent',
                    color: '#1d1c1d'
                  }}
                />
                <button 
                  onClick={sendMessage} 
                  disabled={isProcessing || !input.trim()}
                  style={{
                    width: '32px',
                    height: '32px',
                    borderRadius: '8px',
                    border: 'none',
                    background: isProcessing || !input.trim() ? '#e0e0e0' : 'linear-gradient(135deg, #FF9900 0%, #FF6600 100%)',
                    color: 'white',
                    cursor: isProcessing || !input.trim() ? 'not-allowed' : 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '16px',
                    transition: 'all 0.2s ease',
                    boxShadow: isProcessing || !input.trim() ? 'none' : '0 2px 6px rgba(255,153,0,0.4), inset 0 1px 0 rgba(255,255,255,0.2)'
                  }}
                >
                  {isProcessing ? (
                    <div style={{
                      width: '20px',
                      height: '20px',
                      border: '2px solid #fff',
                      borderTop: '2px solid transparent',
                      borderRadius: '50%',
                      animation: 'spin 1s linear infinite'
                    }}></div>
                  ) : '▶'}
                </button>
              </div>
            </div>
          </>
        )}
        
        {/* Sample Questions Tab */}
        {activeTab === 'questions' && (
          <div style={{ 
            flex: 1,
            overflowY: 'auto',
            padding: '20px'
          }}>
            <div style={{ maxWidth: '900px', margin: '0 auto' }}>
              <div style={{ 
                backgroundColor: '#f0f9ff', 
                padding: '16px 20px', 
                borderRadius: '24px', 
                marginBottom: '24px',
                border: '1px solid #bfdbfe'
              }}>
                <p style={{ color: '#1e40af', margin: 0, fontSize: '14px', fontWeight: '500' }}>
                  💡 Click on any question below to start a conversation
                </p>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '16px' }}>
              {sampleQuestions.map((question, index) => (
                <div 
                  key={index}
                  onClick={() => handleQuestionClick(question)}
                  style={{
                    padding: '24px',
                    backgroundColor: '#fff',
                    border: '1px solid #e5e7eb',
                    borderRadius: '28px',
                    cursor: 'pointer',
                    transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
                    fontSize: '15px',
                    lineHeight: '1.6',
                    position: 'relative',
                    overflow: 'hidden'
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = '#f9fafb';
                    e.currentTarget.style.borderColor = '#0066cc';
                    e.currentTarget.style.transform = 'translateY(-4px)';
                    e.currentTarget.style.boxShadow = '0 12px 24px rgba(0,0,0,0.15)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = '#fff';
                    e.currentTarget.style.borderColor = '#e5e7eb';
                    e.currentTarget.style.transform = 'translateY(0)';
                    e.currentTarget.style.boxShadow = '0 1px 3px rgba(0,0,0,0.1)';
                  }}
                >
                  <div style={{ 
                    position: 'absolute', 
                    top: '12px', 
                    right: '12px', 
                    width: '8px', 
                    height: '8px', 
                    backgroundColor: '#0066cc', 
                    borderRadius: '50%',
                    opacity: 0.6
                  }}></div>
                  {question}
                </div>
              ))}
              </div>
            </div>
          </div>
        )}
        
        {/* Files Tab */}
        {activeTab === 'files' && (
          <div style={{ 
            flex: 1,
            overflowY: 'auto',
            padding: '20px'
          }}>
            <div style={{ maxWidth: '800px', margin: '0 auto' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <p style={{ color: '#666', margin: 0 }}>Visualization files from S3:</p>
                <button 
                  onClick={loadFiles}
                  disabled={loadingFiles}
                  style={{
                    padding: '10px 20px',
                    backgroundColor: '#0066cc',
                    color: 'white',
                    border: 'none',
                    borderRadius: '20px',
                    cursor: loadingFiles ? 'not-allowed' : 'pointer',
                    fontSize: '14px',
                    fontWeight: '500',
                    transition: 'all 0.2s ease'
                  }}
                >
                  {loadingFiles ? 'Loading...' : 'Refresh'}
                </button>
              </div>
              
              {files.length === 0 && !loadingFiles && (
                <div style={{ textAlign: 'center', color: '#666', padding: '40px' }}>
                  No files found. Click Refresh to load files.
                </div>
              )}
              
              {files.map((file, index) => (
                <div 
                  key={index}
                  style={{
                    padding: '20px',
                    margin: '12px 0',
                    backgroundColor: '#fff',
                    border: '1px solid #e5e7eb',
                    borderRadius: '24px',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.08)'
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 'bold', marginBottom: '5px' }}>{file.name}</div>
                    <div style={{ fontSize: '12px', color: '#666' }}>
                      {formatFileSize(file.size)} • {new Date(file.modified).toLocaleString()}
                    </div>
                  </div>
                  <a 
                    href={file.url}
                    download={file.name}
                    style={{
                      padding: '10px 20px',
                      backgroundColor: '#059669',
                      color: 'white',
                      textDecoration: 'none',
                      borderRadius: '20px',
                      fontSize: '14px',
                      fontWeight: '500',
                      transition: 'all 0.2s ease'
                    }}
                  >
                    Download
                  </a>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
      
      <style>{`
        @keyframes pulse {
          0%, 80%, 100% { opacity: 0.3; }
          40% { opacity: 1; }
        }
        
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
        
        input:focus {
          border-color: #0066cc !important;
          box-shadow: 0 0 0 3px rgba(0, 102, 204, 0.1) !important;
        }
        
        button:hover:not(:disabled) {
          transform: translateY(-2px);
          box-shadow: 0 6px 16px rgba(0,0,0,0.2) !important;
        }
      `}</style>
    </>
  );
};

export default Chat;