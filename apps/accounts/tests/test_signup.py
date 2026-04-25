import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

User = get_user_model()


@pytest.mark.django_db
def test_signup_get_renders_form():
    client = Client()
    response = client.get(reverse("signup"))
    assert response.status_code == 200
    assert b"Create account" in response.content


@pytest.mark.django_db
def test_signup_creates_user_and_logs_them_in():
    client = Client()
    response = client.post(
        reverse("signup"),
        {"username": "dad", "password1": "purple-monkey-dishwasher", "password2": "purple-monkey-dishwasher"},
        follow=True,
    )
    assert response.status_code == 200
    assert response.request["PATH_INFO"] == "/"
    assert User.objects.filter(username="dad").exists()
    assert response.context["user"].is_authenticated


@pytest.mark.django_db
def test_signup_with_mismatched_passwords_fails():
    client = Client()
    response = client.post(
        reverse("signup"),
        {"username": "dad", "password1": "purple-monkey-dishwasher", "password2": "different"},
    )
    assert response.status_code == 200
    assert not User.objects.filter(username="dad").exists()


@pytest.mark.django_db
def test_signup_with_too_short_password_fails():
    client = Client()
    response = client.post(
        reverse("signup"),
        {"username": "dad", "password1": "abc", "password2": "abc"},
    )
    assert response.status_code == 200
    assert not User.objects.filter(username="dad").exists()


@pytest.mark.django_db
def test_signup_with_existing_username_fails():
    User.objects.create_user(username="dad", password="x" * 20)
    client = Client()
    response = client.post(
        reverse("signup"),
        {"username": "dad", "password1": "purple-monkey-dishwasher", "password2": "purple-monkey-dishwasher"},
    )
    assert response.status_code == 200
    assert User.objects.filter(username="dad").count() == 1


@pytest.mark.django_db
def test_login_page_links_to_signup():
    client = Client()
    response = client.get(reverse("login"))
    assert response.status_code == 200
    assert reverse("signup").encode() in response.content
