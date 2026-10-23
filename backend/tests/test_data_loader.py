"""ที่มาของค่าลับของ loader ใหม่ (แทน st.secrets) ทำงานแบบเดิม: ลองตาราง [gcp_service_account] ก่อน
แล้วจึงไฟล์ credentials.json และรวมเหตุผลทั้งสองทางเมื่อล้มทั้งคู่ ไม่ต่อเครือข่าย (แทน Credentials/gspread.authorize)

การอ่านชีตและแปลงข้อมูลเทียบตัวเลขแล้วใน test_parity_core (raw_df ตรงทุกบิตกับ loader ต้นฉบับ)
"""
import pytest

from app import config, data_loader

FAKE_TABLE = {"type": "service_account", "project_id": "test-project", "client_email": "test@example.invalid"}


@pytest.fixture
def fake_google(monkeypatch):
    seen = []

    def from_info(info, scopes):
        seen.append(("info", info, scopes))
        return "creds-from-info"

    def from_file(path, scopes):
        seen.append(("file", path, scopes))
        if path == "missing.json":
            raise FileNotFoundError(path)
        return "creds-from-file"

    monkeypatch.setattr(data_loader.Credentials, "from_service_account_info", from_info)
    monkeypatch.setattr(data_loader.Credentials, "from_service_account_file", from_file)
    monkeypatch.setattr(data_loader.gspread, "authorize", lambda creds: ("client", creds))
    return seen


def write_toml(tmp_path, text):
    path = tmp_path / "secrets.toml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_secrets_file_required(monkeypatch):
    monkeypatch.delenv("TFP_SECRETS_FILE", raising=False)
    with pytest.raises(RuntimeError, match="TFP_SECRETS_FILE"):
        config.secrets()


def test_client_from_secrets_table(monkeypatch, tmp_path, fake_google):
    body = "".join(f'{k} = "{v}"\n' for k, v in FAKE_TABLE.items())
    monkeypatch.setenv("TFP_SECRETS_FILE", write_toml(tmp_path, "[gcp_service_account]\n" + body))
    assert data_loader._get_client() == ("client", "creds-from-info")
    assert fake_google == [("info", FAKE_TABLE, data_loader.SCOPES)]


def test_falls_back_to_credentials_file(monkeypatch, tmp_path, fake_google):
    monkeypatch.setenv("TFP_SECRETS_FILE", write_toml(tmp_path, 'GEMINI_API_KEY = "test"\n'))
    monkeypatch.setenv("TFP_CREDENTIALS_FILE", "test-credentials.json")
    assert data_loader._get_client() == ("client", "creds-from-file")
    assert fake_google == [("file", "test-credentials.json", data_loader.SCOPES)]


def test_default_credentials_file_name(monkeypatch):
    monkeypatch.delenv("TFP_CREDENTIALS_FILE", raising=False)
    assert config.credentials_file() == "credentials.json"


def test_both_ways_fail_with_both_reasons(monkeypatch, fake_google):
    monkeypatch.delenv("TFP_SECRETS_FILE", raising=False)
    monkeypatch.setenv("TFP_CREDENTIALS_FILE", "missing.json")
    with pytest.raises(RuntimeError) as e:
        data_loader._get_client()
    assert "TFP_SECRETS_FILE" in str(e.value) and "FileNotFoundError" in str(e.value)
