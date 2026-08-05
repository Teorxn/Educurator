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

function fetchProfile(): Promise<UserProfile> {
  if (!cached) {
    cached = getMyProfile()
      .then(({ data }) => data)
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
}

export function useProfile() {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
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
