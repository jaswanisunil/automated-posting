# Automated Posting API
## Mac Startup & Shutdown Guide

---

## 1. START THE APPLICATION

### Step 1 – Open Docker Desktop

1. Open Docker Desktop on your Mac.
2. Wait until Docker shows that it is running.

### Step 2 – Open Terminal

Copy and execute:

```bash
cd /Users/suniljaswani/Interview/Python/automated-posting
```

### Step 3 – Start the application

Run:

```bash
docker compose up -d
```

**If Dockerfile or dependencies have changed**, rebuild the application:

```bash
docker compose up --build -d
```

### Step 4 – Verify application status

Run:

```bash
docker compose ps
```

To view application logs:

```bash
docker compose logs -f
```

Press `Ctrl + C` to exit the logs. The application will continue running.

---

## 2. OPEN THE API

### Swagger UI – API Documentation

http://127.0.0.1:4000/docs

Use Swagger UI to test the `POST /posting` endpoint.

### Health Check

http://127.0.0.1:4000/health

---

## 3. STOP THE APPLICATION

When you finish working, open Terminal and execute:

```bash
cd /Users/suniljaswani/Interview/Python/automated-posting
```

Then run:

```bash
docker compose down
```

This stops and removes the running containers.

**Note:** Your project files and `.env` file will remain safe.

---

## 4. QUICK COMMAND REFERENCE

| Task | Command |
|---|---|
| Navigate to project | `cd /Users/suniljaswani/Interview/Python/automated-posting` |
| Start application | `docker compose up -d` |
| Rebuild and start | `docker compose up --build -d` |
| Check status | `docker compose ps` |
| View logs | `docker compose logs -f` |
| Stop application | `docker compose down` |

---

## 5. IMPORTANT REMINDERS

- Always start Docker Desktop before starting the application.
- Keep the `.env` file inside the project directory.
- Never commit `.env` or expose API keys and access tokens on GitHub.
- Use `docker compose ps` to check whether the application is running.
- Use `docker compose logs -f` if you face any issues.

---

## PROJECT DETAILS

**Project:** automated-posting

**Technology:** Python, FastAPI, Docker

**Application Port:** 4000

**API Documentation:** http://127.0.0.1:4000/docs
