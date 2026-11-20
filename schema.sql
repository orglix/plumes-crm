-- Extension pour les embeddings futurs (optionnelle mais recommandée)
CREATE EXTENSION IF NOT EXISTS vector;

-- Table des contacts (unifiés)
CREATE TABLE IF NOT EXISTS contacts (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    email VARCHAR(255) UNIQUE,
    instagram_handle VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Table centralisée des messages (Gmail, Instagram, etc.)
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    channel VARCHAR(50) NOT NULL, -- 'gmail', 'instagram', 'spreadsheet'
    external_id VARCHAR(255) UNIQUE NOT NULL, -- ID unique du message chez la source (ex: ID Gmail ou ID message IG)
    thread_id VARCHAR(255), -- Pour regrouper les discussions
    sender VARCHAR(255) NOT NULL,
    recipient VARCHAR(255),
    subject TEXT,
    
    -- Les deux colonnes demandées :
    raw_payload JSONB NOT NULL,    -- Stockage du message brut complet d'origine
    cleaned_content TEXT,          -- Contenu nettoyé (sans HTML, sans signatures lourdes)
    
    direction VARCHAR(20) CHECK (direction IN ('inbound', 'outbound')),
    sent_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index pour accélérer les recherches par canal et par thread
CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(channel);
CREATE INDEX IF NOT EXISTS idx_messages_thread_id ON messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_messages_contact_id ON messages(contact_id);
