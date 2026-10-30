-- Ajout du champ last_seen à la table users
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen TIMESTAMP;

-- Création de la table sensitive_alerts
CREATE TABLE IF NOT EXISTS sensitive_alerts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    user_name VARCHAR(100),
    user_role VARCHAR(50),
    question_text TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    seen BOOLEAN DEFAULT FALSE
);