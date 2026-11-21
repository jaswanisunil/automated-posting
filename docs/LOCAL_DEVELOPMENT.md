# Automated Posting API
## Local Development – Startup & Shutdown Guide

---

## 1. START THE APPLICATION

### Step 1 – Open Docker Desktop

1. Open Docker Desktop on your Mac.
2. Wait until Docker shows that it is running.

### Step 2 – Open Terminal

Navigate to the project directory:

```bash
cd /Users/suniljaswani/Interview/Python/automated-posting
```

### Step 3 – Start Docker

```bash
docker compose up -d
```

If Dockerfile or dependencies have changed, rebuild:

```bash
docker compose up --build -d
```

### Step 4 – Load environment variables

**Important:** Export the variables from `.env` into your Terminal session.

Run these commands:

```bash
set -a
source .env
set +a
```

### Step 5 – Start FastAPI using Uvicorn

```bash
uvicorn app.main:app --host 127.0.0.1 --port 4000 --reload
```

**IMPORTANT:**

- Keep this Terminal window open while using the application.
- Do not press `Ctrl + C` while you are testing the API.
- Uvicorn runs in the foreground and displays application logs in this window.

---

## 2. OPEN SWAGGER UI

Once Uvicorn starts successfully, open:

**Swagger UI:**

http://127.0.0.1:4000/docs

**Health Check:**

http://127.0.0.1:4000/health

Use Swagger UI to test the `POST /posting` endpoint.

---

## 3. VERIFY APPLICATION STATUS

Open a second Terminal window or tab and navigate to the project:

```bash
cd /Users/suniljaswani/Interview/Python/automated-posting
```

Check Docker containers:

```bash
docker compose ps
```

You can also check application logs in the first Terminal window where Uvicorn is running.

---

## 4. STOP THE APPLICATION

When you finish working:

### Step 1 – Stop Uvicorn

Go to the Terminal window running Uvicorn and press:

`Ctrl + C`

### Step 2 – Stop Docker containers

```bash
docker compose down
```

---

## 5. QUICK START COMMANDS

Execute these commands in order whenever you restart your Mac:

**1. Navigate to project:**

```bash
cd /Users/suniljaswani/Interview/Python/automated-posting
```

**2. Start Docker:**

```bash
docker compose up -d
```

**3. Load environment variables:**

```bash
set -a
source .env
set +a
```

**4. Start FastAPI:**

```bash
uvicorn app.main:app --host 127.0.0.1 --port 4000 --reload
```

**5. Open Swagger:**

http://127.0.0.1:4000/docs

---

## 6. IMPORTANT REMINDERS

- Start Docker Desktop before running Docker commands.
- Keep `.env` in the project root directory.
- Never commit `.env` or expose API keys and access tokens on GitHub.
- Keep the Uvicorn Terminal running while testing.
- Use a second Terminal window if you need to run other commands.
- Stop Uvicorn with `Ctrl + C` before stopping Docker.

---

## PROJECT DETAILS

**Project:** automated-posting

**Technology:** Python, FastAPI, Docker

**Application Port:** 4000

**API Documentation:** http://127.0.0.1:4000/docs
