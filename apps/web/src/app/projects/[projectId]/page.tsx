import CreativeStudio from './creative-studio';

export default async function ProjectCreativePage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  return <CreativeStudio projectId={projectId} />;
}
