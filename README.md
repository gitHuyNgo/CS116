# Recommendation System


## 1. Backend
```python
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python -m uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

## 2. Frontend
```python
cd frontend
yarn install

yarn start
```
