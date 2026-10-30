import { redirect } from "next/navigation";
import { auth, isAuthorizedAdminEmail } from "@/auth";

export default async function HomePage() {
  const session = await auth();
  if (isAuthorizedAdminEmail(session?.user?.email)) {
    redirect("/dashboard");
  }
  redirect("/demo");
}

