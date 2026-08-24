# /audit — Firestore Logging + Metrics

**Built in: Stage 7**

Full audit trail stored in Firestore. Every action taken by the system is logged with:
- Timestamp (from SimClock)
- Event type
- Input state and decision rationale
- Outcome
- Compliance check results

Also computes and reports final metrics:
- Net ₹ recovered vs. ₹ at risk
- Diagnosis accuracy (on held-out split)
- Bandit uplift vs. naive baseline (with written caveat about simulated data)
- Exception list of unresolved cases

## Firebase Setup Instructions

### 1. Create a Firebase Project
1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Click "Add project" and follow the wizard
3. Name it something like `ai-revenue-recovery`
4. You can disable Google Analytics (not needed for this project)

### 2. Enable Firestore
1. In your Firebase project, go to **Build → Firestore Database**
2. Click "Create database"
3. Choose **Start in test mode** (for development — switch to production rules before any demo)
4. Select a region close to you (e.g., `asia-south1` for India)

### 3. Download Service Account Credentials
1. Go to **Project Settings → Service accounts**
2. Click "Generate new private key"
3. Save the downloaded JSON file somewhere safe (NOT in the repo — it's in `.gitignore`)

### 4. Set Environment Variables
Copy `.env.example` to `.env` and fill in:

```
GOOGLE_APPLICATION_CREDENTIALS=path/to/your-service-account-key.json
FIREBASE_PROJECT_ID=your-project-id
```

### 5. Verify Setup
Run the SimClock test to verify Firestore connectivity:

```bash
pytest simclock/test_simclock.py -v
```
