"""Inventory master-data forms (Sprint 12, ADR-039)."""

from django import forms

from apps.inventory.models import Warehouse


class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ["company", "code", "name", "is_active"]
        labels = {"company": "شرکت", "code": "کد انبار", "name": "نام انبار", "is_active": "فعال"}
