import { useEffect, useState } from "react";
import { getMyProfile } from "./api/account";
import type { UserProfile } from "./api/account";

/**
 * Perfil del usuario autenticado, cacheado a nivel de módulo.
 *
 * Varias pantallas necesitan el rol (para mostrar columnas o secciones de
 * administración); sin la caché cada una dispararía su propia petición a
 * `/api/users/me` en cada montaje.
 */
let cached: Promise<UserProfile> | null = null;
// Además de la promesa se guarda el valor ya resuelto: así un componente que
// monta más tarde arranca con el perfil puesto en vez de renderizar una vez
// sin él. Eso es lo que hacía aparecer la columna «Subido por» de la tabla de
// documentos un instante después de pintarla, moviendo el resto de columnas.
let resolvedProfile: UserProfile | null = null;

function fetchProfile(): Promise<UserProfile> {
  if (!cached) {
    cached = getMyProfile()
      .then(({ data }) => {
        resolvedProfile = data;
        return data;
      })
      .catch((err) => {
        cached = null; // un fallo no debe quedar cacheado para siempre
        throw err;
      });
  }
  return cached;
}

/** Borra la caché al cerrar sesión, para que el siguiente login no herede el perfil anterior. */
export function clearProfileCache() {
  cached = null;
  resolvedProfile = null;
}

export function useProfile() {
  const [profile, setProfile] = useState<UserProfile | null>(resolvedProfile);
  const [loading, setLoading] = useState(resolvedProfile === null);

  useEffect(() => {
    if (resolvedProfile) return;
    let alive = true;
    fetchProfile()
      .then((p) => alive && setProfile(p))
      .catch(() => {})
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  return { profile, loading, isAdmin: profile?.role === "admin" };
}
