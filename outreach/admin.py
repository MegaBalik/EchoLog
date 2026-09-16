from django.contrib import admin

from .models import Batch, Contact, GmailSyncState, Recipient, SenderAccount


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('display_name_admin', 'company', 'email', 'country', 'domain', 'do_not_contact', 'bounced')
    search_fields = ('name', 'company', 'email', 'country', 'domain', 'website', 'note')
    list_filter = ('country', 'do_not_contact', 'bounced')
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description='Name', ordering='name')
    def display_name_admin(self, obj):
        return obj.display_name


@admin.register(SenderAccount)
class SenderAccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'daily_limit', 'active', 'created_at')
    list_filter = ('active',)
    search_fields = ('name', 'email')
    readonly_fields = ('token_file', 'created_at', 'updated_at')


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ('name', 'sender_account', 'status', 'created_at', 'started_at', 'daily_limit')
    list_filter = ('status', 'sender_account')
    search_fields = ('name', 'subject', 'sender_account__name', 'sender_account__email')


@admin.register(Recipient)
class RecipientAdmin(admin.ModelAdmin):
    list_display = ('contact', 'batch', 'sender_account', 'status', 'hope', 'sent_at', 'replied_at')
    list_filter = ('status', 'hope', 'batch', 'sender_account', 'contact__country')
    search_fields = ('contact__name', 'contact__company', 'contact__email', 'contact__domain', 'batch__name')
    raw_id_fields = ('contact', 'batch')


@admin.register(GmailSyncState)
class GmailSyncStateAdmin(admin.ModelAdmin):
    list_display = ('sender_account', 'history_id', 'updated_at')
    readonly_fields = ('updated_at',)
