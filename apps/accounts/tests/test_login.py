import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

User = get_user_model()


@pytest.mark.django_db
def test_anonymous_request_to_settings_redirects_to_login():
    client = Client()
    response = client.get(reverse("settings"))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("login"))


@pytest.mark.django_db
def test_anonymous_request_to_root_redirects_to_login():
    client = Client()
    response = client.get("/")
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("login"))


@pytest.mark.django_db
def test_login_with_valid_credentials_lands_on_dashboard():
    User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    client = Client()
    response = client.post(reverse("login"), {"username": "alice", "password": "correct-horse-battery-staple"}, follow=True)
    assert response.status_code == 200
    assert response.request["PATH_INFO"] == "/"


@pytest.mark.django_db
def test_login_with_bad_password_stays_on_login():
    User.objects.create_user(username="alice", password="correct-horse-battery-staple")
    client = Client()
    response = client.post(reverse("login"), {"username": "alice", "password": "wrong"})
    assert response.status_code == 200
    assert b"Sign in" in response.content


@pytest.mark.django_db
def test_healthz_returns_ok_without_auth():
    client = Client()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.content == b"ok"
