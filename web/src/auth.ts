import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import { isAuthorizedAdminEmail } from "@/lib/auth-guard";

export { isAuthorizedAdminEmail };

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google],
  session: { strategy: "jwt" },
  pages: {
    error: "/demo",
  },
  callbacks: {
    async signIn({ user }) {
      return isAuthorizedAdminEmail(user?.email);
    },
    async session({ session }) {
      return session;
    },
  },
});
