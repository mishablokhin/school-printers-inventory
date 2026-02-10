# School Cartridges SSO

A web-based inventory management system for tracking printers and cartridge stock in a school or educational organization.  
The application is designed for internal IT and administrative use and integrates with **Nextcloud** for authentication via **OpenID Connect (OIDC)**.

The project started as a minimal SSO-enabled Django skeleton and evolved into a full-featured inventory system with per-building storage, printer–cartridge compatibility, and a detailed transaction journal.

---

## ✨ Key Features

- 🔐 **Single Sign-On via Nextcloud (OIDC)**
  - Login using existing Nextcloud accounts
  - Automatic user profile creation
  - User full name is taken from Nextcloud profile data

- 🖨 **Printer & Cartridge Inventory**
  - Manage buildings, rooms, printers, printer models, and cartridge models
  - Define compatibility between printers and cartridges
  - Track stock globally and per building

- 📦 **Stock Management**
  - Incoming stock (warehouse replenishment)
  - Outgoing stock (issuance to specific printers)
  - Automatic stock balance updates
  - Server-side validation to prevent negative balances

- 📖 **Transaction Journal**
  - Full history of all stock movements
  - Search by cartridge, printer, building, or responsible person

- 🐳 **Docker-based Deployment**
  - Separate configurations for development and production
  - One-command startup via `make`

---

## 🧩 Technology Stack

- **Backend:** Django  
- **Authentication:** Nextcloud OpenID Connect (via `django-allauth`)  
- **Database:** PostgreSQL (recommended), SQLite for local development  
- **Reverse Proxy:** Caddy  
- **Containerization:** Docker & Docker Compose  
- **Frontend:** Django Templates + Bootstrap Icons  

---

## 🚀 Quick Start (Local Development)

### 1) Copy environment variables

```bash
cp .env .env
```

### 2) Configure OIDC credentials
Fill in the following variables in .env:
	•	**OIDC_SERVER_URL**
	•	**OIDC_CLIENT_ID**
	•	**OIDC_CLIENT_SECRET**

Also fill DB and Django paramaters

These values are provided by your Nextcloud administrator.

### 3) Start the development stack
```bash
make up
```

### 4) View service
**Open in your browser: http://localhost:5007**

## 🎯 Intended Use

This project is intended for:
- School IT departments
- Educational institutions
- Internal inventory and asset tracking
- Environments with centralized authentication via Nextcloud

It is not designed as a public SaaS product but as a reliable internal tool.