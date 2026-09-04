# Setup Guide

## Prerequisites

- Python 3.11+
- Node.js 18+
- A Firebase project with Firestore enabled
- A Sarvam AI account (free: ₹100 credits on signup at dashboard.sarvam.ai)

## 1. Clone and install

```bash
git clone https://github.com/kavyachetwani/AIRevenueRecovery.git
cd AIRevenueRecovery
```

### Python dependencies

```bash
pip install -r requirements.txt
```

### Dashboard dependencies

```bash
cd dashboard
npm install
cd ..
```

## 2. Environment variables

Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
```

Required variables:

```dotenv
# Firebase / Firestore
GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/firebase-service-account.json
FIREBASE_PROJECT_ID=your-project-id

# Sarvam AI (for Hinglish escalation agent)
SARVAM_API_KEY=your-sarvam-api-key

# SimClock
SIMCLOCK_ANCHOR=2026-01-01T00:00:00
```

### Firebase setup

1. Go to console.firebase.google.com
2. Create a project (or use an existing one)
3. Enable Firestore Database (start in test mode for development)
4. Go to Project Settings then Service Accounts then Generate New Private Key
5. Save the JSON file somewhere safe (not in the repo)
6. Set `GOOGLE_APPLICATION_CREDENTIALS` to the path of that JSON file

### Sarvam AI setup

1. Go to dashboard.sarvam.ai and sign up
2. You get ₹100 free credits (more than enough)
3. Generate an API key
4. Set `SARVAM_API_KEY` in your `.env`

### Dashboard Firebase config

The dashboard needs its own Firebase config. Create `dashboard/.env`:

```dotenv
VITE_FIREBASE_API_KEY=your-firebase-web-api-key
VITE_FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=your-project-id
VITE_FIREBASE_STORAGE_BUCKET=your-project.appspot.com
VITE_FIREBASE_MESSAGING_SENDER_ID=your-sender-id
VITE_FIREBASE_APP_ID=your-app-id
VITE_API_URL=http://localhost:8000
```

You can find these values in Firebase Console then Project Settings then General then Your apps then Web app config.

## 3. Generate synthetic data

```bash
python data/generate_payments.py
python data/generate_retry_outcomes.py
python data/split_data.py
```

This produces 500 payment records and 1,200 retry outcome records, calibrated against published NPCI/RBI data.

## 4. Initialize the diagnosis database

```bash
python diagnosis/db.py
```

## 5. Run the system

You need two terminals:

**Terminal 1 (Backend):**

```bash
cd backend
uvicorn main:app --reload --port 8000
```

**Terminal 2 (Dashboard):**

```bash
cd dashboard
npm run dev
```

Open http://localhost:5173 in your browser.

## 6. Running tests

```bash
python -m pytest tests/ -v
```

69 tests across 7 test suites.

## 7. Running audit scripts (CLI)

These read from Firestore and produce the same metrics the dashboard shows:

```bash
python audit/metrics.py
python audit/exceptions.py
python audit/summary.py
```
