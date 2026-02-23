from fastapi import HTTPException, status


class ChatServiceError(HTTPException):
    def __init__(self, detail: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
        super().__init__(status_code=status_code, detail=detail)


class GroupNotFoundError(ChatServiceError):
    def __init__(self):
        super().__init__(detail="Gruppo non trovato", status_code=status.HTTP_404_NOT_FOUND)


class NotAMemberError(ChatServiceError):
    def __init__(self):
        super().__init__(detail="Non sei membro di questo gruppo", status_code=status.HTTP_403_FORBIDDEN)


class InsufficientPermissionsError(ChatServiceError):
    def __init__(self):
        super().__init__(detail="Permessi insufficienti", status_code=status.HTTP_403_FORBIDDEN)


class InvalidInviteCodeError(ChatServiceError):
    def __init__(self):
        super().__init__(detail="Codice di invito non valido o scaduto", status_code=status.HTTP_400_BAD_REQUEST)


class MessageNotFoundError(ChatServiceError):
    def __init__(self):
        super().__init__(detail="Messaggio non trovato", status_code=status.HTTP_404_NOT_FOUND)


class AlreadyMemberError(ChatServiceError):
    def __init__(self):
        super().__init__(detail="Sei già membro di questo gruppo", status_code=status.HTTP_409_CONFLICT)


class StorageLimitError(ChatServiceError):
    def __init__(self):
        super().__init__(
            detail="Limite di archiviazione raggiunto, impossibile completare l'operazione",
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
        )


class CannotDeleteDefaultGroupError(ChatServiceError):
    def __init__(self):
        super().__init__(
            detail="Impossibile eliminare il gruppo pubblico predefinito",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
