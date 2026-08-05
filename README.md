# hktAntennaWorkflow

# Project Setup

## 1. Set Up a Virtual Environment

```bash
python -m venv venv
```

## 2. Install Required Packages

```bash
pip install <required-packages>
```

## 3. Create `requirements.txt`

```bash
pip freeze > requirements.txt
```

## 4. Create `.gitignore`

Example:

```gitignore
venv/
__pycache__/
.ipynb_checkpoints/
.env
```

---

# Client Setup (Notebook)

> Steps 1–5 must be completed outside the notebook.
>
> **Note:** A notebook cannot activate its own virtual environment.

## 1. Install Ollama

Download and install Ollama on your machine.

## 2. Clone the Repository

```bash
git clone <repository-url>
```

## 3. Navigate to the Repository

```bash
cd <repository-name>
```

## 4. Create a Virtual Environment

```bash
python -m venv venv
```

## 5. Activate the Virtual Environment

**Windows**

```bash
.\venv\Scripts\activate
```

## 6. Install Dependencies

```bash
pip install -r requirements.txt
```

## 7. Create a Jupyter Kernel

```bash
python -m ipykernel install --user --name workflow-venv --display-name "Python (workflow-venv)"
```

## 8. Enter API Keys

Add all required API keys to the appropriate configuration file or environment variables.

## 9. Run the Notebook

Run all notebook cells.

---

# Website and Web Server Application

## Server Side

### Notes

- Each client must have a unique ID to ensure requests and generated results are kept separate.
- Use **Flask** for local deployment (accessible only from the host computer).
- Use **Waitress** for network deployment (accessible to devices on the same Wi-Fi network).
- Install **Ollama** before running the application.

### Setup Steps

#### 1. Create a Virtual Environment

```bash
python -m venv venv
```

#### 2. Activate the Virtual Environment

```bash
.\venv\Scripts\activate
```

#### 3. Clone the Repository

```bash
git clone <repository-url>
```

#### 4. Navigate to the Repository

```bash
cd <repository-name>
```

#### 5. Install Dependencies

```bash
pip install -r requirements.txt
```

#### 6. Start the Application

```bash
python app.py
```

#### 7. Find the Server Address

Run:

```bash
ipconfig
```

Locate the **IPv4 Address** and append port **5000**.

Example:

```text
192.168.1.100:5000
```

---

## Client Access

1. Open a web browser.
2. Enter the server address:

```text
http://<IPv4-Address>:5000
```

Example:

```text
http://192.168.1.100:5000
```

3. Start using the application.
