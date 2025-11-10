from rest_framework import serializers
from .models import PartyMenuItem, SeatSelection, Seat, Table, Modifier, MenuItem


class ModifierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Modifier
        fields = ("id", "name")


class MenuItemSerializer(serializers.ModelSerializer):
    modifiers = ModifierSerializer(many=True, read_only=True)

    class Meta:
        model = MenuItem
        fields = ("id", "name", "price", "modifiers")


class PartyMenuItemSerializer(serializers.ModelSerializer):
    menu_item = MenuItemSerializer(read_only=True)

    class Meta:
        model = PartyMenuItem
        fields = ("id", "menu_item", "available", "price_override")


class SeatSelectionSerializer(serializers.ModelSerializer):
    modifier_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Modifier.objects.all(), source="modifiers"
    )
    item_id = serializers.PrimaryKeyRelatedField(
        queryset=MenuItem.objects.all(), source="item"
    )

    class Meta:
        model = SeatSelection
        fields = ("id", "item_id", "modifier_ids")


class SeatSerializer(serializers.ModelSerializer):
    cart = SeatSelectionSerializer(many=True, read_only=True, source="seatselection_set")

    class Meta:
        model = Seat
        fields = ("id", "number", "cart")