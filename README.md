# AI Supply Chain Demand Forecasting

## Overview

AI Supply Chain Demand Forecasting is a Django-based web application designed to help businesses forecast product demand, monitor inventory, generate reports, and manage supply chain operations through an interactive dashboard.

The system provides:

* Demand forecasting
* Inventory monitoring
* Owner/Admin dashboards
* Report generation
* User authentication and management
* Analytics and business insights

---

## Features

### Demand Forecasting

* Predict future product demand
* Forecast trends based on historical data
* Fallback forecasting logic when trained model is unavailable

### Inventory Management

* Track inventory levels
* Monitor stock availability
* Identify potential shortages

### User Management

* User registration
* Login and authentication
* Owner dashboard access

### Reports

* Generate business reports
* Export and analyze forecasting results

### Dashboard Analytics

* Visual insights
* Business performance monitoring
* Forecast summaries

---

## Technology Stack

### Backend

* Django
* Python

### Data Science

* Pandas
* NumPy
* Scikit-Learn

### Frontend

* HTML
* CSS
* JavaScript

### Database

* SQLite

---

## Project Structure

```text
core/
forecasting/
ownerpanel/
static/
templates/
manage.py
requirements.txt
```

---

## Installation

Clone the repository:

```bash
git clone https://github.com/Prajapati-Harsh-224/AI-Supply-Chain-Demand-Forecasting.git
cd AI-Supply-Chain-Demand-Forecasting
```

Create virtual environment:

```bash
python -m venv .venv
```

Activate virtual environment:

Windows:

```bash
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run migrations:

```bash
python manage.py migrate
```

Start the server:

```bash
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000
```

---

## Live Demo

https://ai-supply-chain-demand-forecasting.onrender.com

---

## GitHub Repository

https://github.com/Prajapati-Harsh-224/AI-Supply-Chain-Demand-Forecasting

---

## Note

The trained Random Forest model file (`demand_forecast_model.pkl`) is intentionally excluded from the repository because of its large size. The deployed application uses fallback forecasting logic when the model file is unavailable.

---

## Future Improvements

* Deploy trained forecasting model
* Advanced analytics dashboard
* Multiple forecasting algorithms
* Cloud database integration
* Enhanced reporting system

---

## Author

Harsh Prajapati

AI / Machine Learning Enthusiast
