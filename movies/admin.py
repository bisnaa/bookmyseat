from django.contrib import admin
from .models import Movie, Theater, Seat,Booking,Payment
from .models import Genre, Language

admin.site.register(Genre)
admin.site.register(Language)
@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ['name', 'rating', 'cast','description']

@admin.register(Theater)
class TheaterAdmin(admin.ModelAdmin):
    list_display = ['name', 'movie', 'time']

@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ['theater', 'seat_number', 'is_booked']

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['user', 'seat', 'movie','theater','booked_at']
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        'user',
        'amount',
        'status',
        'created_at'
    ]